"""The agent team. Each function is one agent with one job.

Inbox triage   -> classify new mail into needs_you / fyi / noise
Follow-ups     -> sent mail with no reply after N days
Calendar       -> today's events, overlaps, free blocks
Goals          -> IBM goals/MyScore/learning matched to free time
Briefing       -> the morning brief
Drafting       -> replies in your voice (never sent without approval)
Orchestrator   -> chat: understands a request and calls the others
"""
import json
from datetime import date, datetime, timedelta, timezone

from . import ai, db, ibm, outlook
from .config import settings

NOISE_HINTS = ("noreply", "no-reply", "newsletter", "notification", "donotreply", "mailer", "digest")


def outlook_ok():
    try:
        return outlook.status()["state"] == "connected"
    except Exception:
        return False


# ---------- Inbox triage ----------
def _rule_triage(e):
    s = settings()
    sender = (e["sender_email"] or "").lower()
    text = f"{e['subject']} {e['preview']}".lower()
    if sender in [v.lower() for v in s["vips"]]:
        return "needs_you", "From a VIP"
    if any(h in sender for h in NOISE_HINTS):
        return "noise", "Automated sender"
    if "?" in text or any(w in text for w in ("can you", "could you", "please", "by friday", "by eod",
                                               "asap", "deadline", "approve", "confirm", "action required")):
        return "needs_you", "Asks you something"
    return "fyi", "No question for you"


def triage():
    pending = db.q("SELECT * FROM emails WHERE triaged=0 ORDER BY received DESC LIMIT 40")
    if not pending:
        return 0
    results = {}
    if ai.configured():
        try:
            payload = [{"id": e["id"], "from": f"{e['sender_name']} <{e['sender_email']}>",
                        "subject": e["subject"], "preview": e["preview"][:400]} for e in pending]
            data = ai.complete_json(
                f"You triage email for {settings()['name']}. For each email decide: needs_you (a person expects her "
                "answer or action), fyi (worth knowing, no action), or noise (automated, marketing). "
                "Extract a one-line task if there is one and a due date if stated. "
                'Return {"emails":[{"id":str,"category":str,"reason":str,"task":str,"due":"YYYY-MM-DD" or null}]}',
                f"Today is {date.today().isoformat()}. VIPs: {settings()['vips']}\n" + json.dumps(payload))
            results = {r["id"]: r for r in data.get("emails", [])}
        except Exception as ex:
            db.log("triage", f"AI triage failed, using rules: {ex}")
    for e in pending:
        r = results.get(e["id"])
        if r and r.get("category") in ("needs_you", "fyi", "noise"):
            cat, reason, task, due = r["category"], r.get("reason", ""), r.get("task", ""), r.get("due")
        else:
            (cat, reason), task, due = _rule_triage(e), "", None
        db.x("UPDATE emails SET category=?, reason=?, task=?, due=?, triaged=1 WHERE id=?",
             (cat, reason, task, due, e["id"]))
    db.log("triage", f"Triaged {len(pending)} emails")
    return len(pending)


def needs_you():
    rows = db.q("""SELECT * FROM emails WHERE category='needs_you' AND handled=0 ORDER BY received DESC LIMIT 20""")
    replied = {r["conversation_id"] for r in db.q("SELECT conversation_id, MAX(sent) s FROM sent GROUP BY conversation_id")}
    out = []
    for e in rows:
        # if you've already replied after this email arrived, it no longer needs you
        last = db.q("SELECT MAX(sent) s FROM sent WHERE conversation_id=?", (e["conversation_id"],))[0]["s"]
        if e["conversation_id"] in replied and last and last > e["received"]:
            continue
        out.append(e)
    return out


# ---------- Follow-ups ----------
def waiting_on():
    days = settings()["followup_days"]
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    out = []
    for s in db.q("SELECT * FROM sent WHERE sent < ? ORDER BY sent DESC LIMIT 60", (cutoff,)):
        if not s["to_email"] or s["to_email"] == "":
            continue
        reply = db.q("SELECT 1 FROM emails WHERE conversation_id=? AND received > ?", (s["conversation_id"], s["sent"]))
        later_sent = db.q("SELECT 1 FROM sent WHERE conversation_id=? AND sent > ?", (s["conversation_id"], s["sent"]))
        if reply or later_sent:
            continue
        looks_like_ask = "?" in (s["preview"] or "") or any(w in (s["preview"] or "").lower()
                                                             for w in ("let me know", "could you", "can you", "please"))
        if not looks_like_ask:
            continue
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(s["sent"].replace("Z", "+00:00"))).days
        s["days"] = age
        out.append(s)
    return out[:10]


# ---------- Calendar ----------
def _local_now():
    return datetime.now()


def _hm(s):
    return datetime.strptime(s[-5:], "%H:%M")


def calendar_today():
    evs = outlook.events() if outlook_ok() else []
    s = settings()
    # overlaps
    for i, e in enumerate(evs):
        e["overlap"] = any(o is not e and o["start"] < e["end"] and e["start"] < o["end"] for o in evs)
    # free blocks of 30+ minutes inside working hours
    free, cursor = [], s["work_start"]
    for e in sorted(evs, key=lambda e: e["start"]):
        st, en = e["start"][-5:], e["end"][-5:]
        if st > cursor and (_hm(st) - _hm(cursor)).seconds >= 1800 and st <= s["work_end"]:
            free.append({"start": cursor, "end": min(st, s["work_end"])})
        cursor = max(cursor, en)
    if cursor < s["work_end"] and (_hm(s["work_end"]) - _hm(cursor)).seconds >= 1800:
        free.append({"start": cursor, "end": s["work_end"]})
    now = _local_now().strftime("%H:%M")
    free = [{"start": max(f["start"], now), "end": f["end"]} for f in free if f["end"] > now]
    free = [f for f in free if (_hm(f["end"]) - _hm(f["start"])).seconds >= 1800]
    return evs, free


# ---------- Goals ----------
def goal_actions(free):
    items = ibm.open_items()
    acts = []
    # suggest focused blocks of at most an hour, each goal getting a different slot where possible
    slots = []
    for f in free:
        st = f["start"]
        while (_hm(f["end"]) - _hm(st)).seconds >= 1800 and len(slots) < 6:
            en = min(f["end"], (_hm(st) + timedelta(hours=1)).strftime("%H:%M"))
            slots.append({"start": st, "end": en})
            st = en
    # full hours first, then earliest
    slots.sort(key=lambda s: (-(_hm(s["end"]) - _hm(s["start"])).seconds, s["start"]))
    def urgency_of(it):
        d = it["days_left"]
        return ("overdue" if d is not None and d < 0 else
                "due soon" if d is not None and d <= 14 else
                "required, not met" if it["status"] == "Not Met" else "on the list")
    order = {"overdue": 0, "due soon": 1, "required, not met": 2, "on the list": 3}
    items.sort(key=lambda it: order[urgency_of(it)])  # stable: keeps soonest-first inside each group
    for it in items[:6]:
        urgency = urgency_of(it)
        slot = slots.pop(0) if slots and urgency != "on the list" else None
        suggestion = (f"Use {slot['start']}–{slot['end']} today" if slot
                      else "Plan a block this week" if urgency != "on the list" else "")
        acts.append({**it, "urgency": urgency, "suggestion": suggestion, "slot": slot})
    return acts


# ---------- Briefing ----------
def gather():
    evs, free = calendar_today()
    return {"needs": needs_you(), "waiting": waiting_on(), "events": evs, "free": free,
            "goals": goal_actions(free), "outlook": outlook_ok(), "ai": ai.configured()}


def _plain_brief(g):
    s = settings()
    parts = [f"Good morning, {s['name']}."]
    n = len(g["needs"])
    if g["outlook"]:
        parts.append(f"{n} email{'s' if n != 1 else ''} need{'s' if n == 1 else ''} your answer" +
                     (f", starting with {g['needs'][0]['sender_name']} about \"{g['needs'][0]['subject']}\"." if n else "."))
        if g["waiting"]:
            w = g["waiting"][0]
            parts.append(f"You're waiting on {len(g['waiting'])} repl{'y' if len(g['waiting']) == 1 else 'ies'}; "
                         f"{w['to_name'] or w['to_email']} hasn't answered in {w['days']} days.")
        parts.append(f"You have {len(g['events'])} meeting{'s' if len(g['events']) != 1 else ''} today.")
        if any(e["overlap"] for e in g["events"]):
            parts.append("Two of them overlap.")
    else:
        parts.append("Outlook isn't connected yet, so I can't see your mail or calendar.")
    urgent = [a for a in g["goals"] if a["urgency"] != "on the list"]
    if urgent:
        a = urgent[0]
        when = f"due in {a['days_left']} days" if a["days_left"] is not None else a["urgency"]
        parts.append(f"On your IBM goals, {a['title']} is {when}." + (f" {a['suggestion']}." if a["suggestion"] else ""))
    elif not g["goals"]:
        parts.append("Drop your Goals, MyScore and YourLearning pages in the IBM folder and I'll track them.")
    return " ".join(parts)


def brief(force=False):
    today = date.today().isoformat()
    if not force:
        row = db.q("SELECT text FROM briefs WHERE day=?", (today,))
        if row:
            return row[0]["text"]
    g = gather()
    text = _plain_brief(g)
    if ai.configured():
        try:
            text = ai.complete(
                f"You are J.A.R.V.I.S., {settings()['name']}'s assistant. Write her morning brief: 4-6 short "
                "sentences, spoken aloud, warm and crisp. Lead with what needs her, then meetings, then the single "
                "most useful thing she can do today for her IBM goals using a free block. No lists, no markdown.",
                [{"role": "user", "content": json.dumps(_compact(g), default=str)}], max_tokens=400)
        except Exception as e:
            db.log("brief", f"AI brief failed, using plain brief: {e}")
    db.x("INSERT OR REPLACE INTO briefs(day,text,created) VALUES(?,?,?)", (today, text, db.now_iso()))
    db.log("brief", "Morning brief ready")
    return text


def _compact(g):
    return {"needs_you": [{"from": e["sender_name"], "subject": e["subject"], "task": e["task"], "due": e["due"]} for e in g["needs"][:6]],
            "waiting_on": [{"to": w["to_name"], "subject": w["subject"], "days": w["days"]} for w in g["waiting"][:5]],
            "meetings": [{"time": e["start"][-5:], "title": e["subject"], "overlap": e["overlap"]} for e in g["events"]],
            "free_blocks": g["free"], "ibm_goals": [{"title": a["title"], "source": a["source"], "status": a["status"],
                                                      "days_left": a["days_left"], "detail": a["detail"]} for a in g["goals"]],
            "outlook_connected": g["outlook"], "today": date.today().isoformat()}


# ---------- Drafting ----------
def _voice_samples():
    rows = db.q("SELECT preview FROM sent ORDER BY sent DESC LIMIT 6")
    return "\n---\n".join(r["preview"] for r in rows if r["preview"])


def draft_reply(email_id, instructions=""):
    e = db.q("SELECT * FROM emails WHERE id=?", (email_id,))
    if not e:
        raise ValueError("I couldn't find that email.")
    e = e[0]
    name = settings()["name"]
    if ai.configured():
        body = ai.complete(
            f"You draft email replies as {name}. Match her tone from these samples of her sent mail:\n"
            f"{_voice_samples() or '(no samples yet: be warm, brief and professional)'}\n"
            "Write only the reply body. Don't invent facts, dates or commitments; use [brackets] for anything she must fill in.",
            [{"role": "user", "content": f"From: {e['sender_name']}\nSubject: {e['subject']}\n\n{e['preview']}\n\n"
                                         f"Her instructions: {instructions or 'reply helpfully'}"}], max_tokens=600)
    else:
        body = f"Hi {(e['sender_name'] or '').split(' ')[0]},\n\nThanks for your note about \"{e['subject']}\". [Your reply]\n\nBest,\n{name}"
    did = db.x("""INSERT INTO drafts(kind,ref_id,to_name,to_email,subject,body,status,created)
                  VALUES('reply',?,?,?,?,?,'pending',?)""",
               (email_id, e["sender_name"], e["sender_email"], "RE: " + e["subject"], body, db.now_iso()))
    return {"id": did, "to_name": e["sender_name"], "subject": "RE: " + e["subject"], "body": body}


def draft_nudge(sent_id):
    s = db.q("SELECT * FROM sent WHERE id=?", (sent_id,))[0]
    first = (s["to_name"] or "").split(" ")[0] or "there"
    body = (ai.complete(f"Write a short, friendly follow-up nudge as {settings()['name']}. 2-3 sentences, body only.",
                        [{"role": "user", "content": f"Original to {s['to_name']}, subject {s['subject']}, sent {s['days'] if 'days' in s else ''} days ago:\n{s['preview']}"}],
                        max_tokens=250)
            if ai.configured() else
            f"Hi {first},\n\nJust following up on my note about \"{s['subject']}\". Let me know when you get a chance.\n\nThanks,\n{settings()['name']}")
    did = db.x("""INSERT INTO drafts(kind,ref_id,to_name,to_email,subject,body,status,created)
                  VALUES('nudge',?,?,?,?,?,'pending',?)""",
               (sent_id, s["to_name"], s["to_email"], "RE: " + s["subject"], body, db.now_iso()))
    return {"id": did, "to_name": s["to_name"], "subject": "RE: " + s["subject"], "body": body}


def approve_draft(draft_id, body):
    """The only path that sends email. Called when you click 'Approve and send'."""
    d = db.q("SELECT * FROM drafts WHERE id=?", (draft_id,))[0]
    if d["kind"] == "reply":
        oid = outlook.create_reply_draft(d["ref_id"], body)
        outlook.send_draft(oid)
        db.x("UPDATE emails SET handled=1 WHERE id=?", (d["ref_id"],))
    else:
        # reply-all on your own sent message keeps the thread and goes to the original recipients
        oid = outlook.create_reply_draft(d["ref_id"], body, reply_all=True)
        outlook.send_draft(oid)
        db.x("UPDATE sent SET nudged=1 WHERE id=?", (d["ref_id"],))
    db.x("UPDATE drafts SET status='sent', body=? WHERE id=?", (body, draft_id))
    db.log("send", f"Sent to {d['to_name'] or d['to_email']}: {d['subject']}")


def save_to_outlook_drafts(draft_id, body):
    d = db.q("SELECT * FROM drafts WHERE id=?", (draft_id,))[0]
    outlook.create_reply_draft(d["ref_id"], body, reply_all=d["kind"] == "nudge")
    db.x("UPDATE drafts SET status='saved', body=? WHERE id=?", (body, draft_id))


# ---------- Orchestrator (chat) ----------
def chat(message, history=None):
    g = gather()
    agents = ["brief"]
    m = message.lower()
    for key, ag in (("draft", "draft"), ("reply", "draft"), ("email", "triage"), ("inbox", "triage"),
                    ("wait", "follow"), ("follow", "follow"), ("nudge", "follow"), ("meeting", "cal"),
                    ("calendar", "cal"), ("schedule", "cal"), ("goal", "goals"), ("myscore", "goals"),
                    ("learning", "goals"), ("course", "goals"), ("badge", "goals")):
        if key in m and ag not in agents:
            agents.append(ag)
    if not ai.configured():
        return {"text": "I need an AI key to answer freely. Open Settings and add your ICA key. "
                        "Until then, try \"give me my brief\".", "agents": agents, "action": None}
    system = (
        f"You are J.A.R.V.I.S., {settings()['name']}'s proactive work assistant at IBM. You can see her live state below. "
        "Answer in 1-4 spoken sentences, no markdown. You may propose actions but never claim to have sent email or "
        "changed her calendar: those need her approval. If she asks you to draft a reply, set action to "
        '{"type":"draft","email_id":...,"instructions":...}. If she asks to block time, set action to '
        '{"type":"block","title":...,"start":"HH:MM","end":"HH:MM"}. '
        'Return JSON: {"text": str, "action": object or null}.\n\nState:\n' + json.dumps(_compact(g), default=str) +
        "\nEmail ids for drafting: " + json.dumps([{"id": e["id"], "from": e["sender_name"], "subject": e["subject"]} for e in g["needs"]]))
    msgs = (history or [])[-8:] + [{"role": "user", "content": message}]
    raw = ai.complete(system, msgs, max_tokens=600)
    try:
        import re
        data = json.loads(re.search(r"\{.*\}", raw, re.S).group(0))
    except Exception:
        data = {"text": raw, "action": None}
    return {"text": data.get("text", raw), "action": data.get("action"), "agents": agents}


# ---------- scheduled jobs ----------
def sync_job():
    if outlook_ok():
        try:
            outlook.sync_mail()
            triage()
        except Exception as e:
            db.log("sync", f"Mail sync failed: {e}")
    try:
        ibm.scan()
    except Exception as e:
        db.log("ibm", f"Folder scan failed: {e}")


def brief_job():
    sync_job()
    text = brief(force=True)
    s = settings()
    if s.get("brief_email") and outlook_ok():
        try:
            me = outlook._get("/me")["mail"]
            outlook.send_mail(me, f"Your morning brief, {date.today():%A %B %-d}", text)
        except Exception as e:
            db.log("brief", f"Couldn't email the brief: {e}")
