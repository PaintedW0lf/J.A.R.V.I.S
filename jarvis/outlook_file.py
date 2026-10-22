"""Schedule-from-file mode: no Outlook connection at all.

Jarvis reads your calendar (and, optionally, sample or exported email) from JSON files in
the IBM Drop folder:

  schedule.json   {"events": [{"title","date":"YYYY-MM-DD" or "day":"Mon","start":"HH:MM","end":"HH:MM"}]}
  demo_mail.json  {"emails": [{"from_name","from_email","subject","body","hours_ago"}],
                   "sent":   [{"to_name","to_email","subject","body","days_ago"}]}

Edit the files, and Jarvis picks the changes up on the next sync (every 5 minutes, or press Refresh).
Nothing is ever sent from this mode: "Approve and send" only records your approval.
"""
import json
from datetime import datetime, timedelta, timezone

from . import db
from .config import drop_folder

DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _load(name):
    p = drop_folder() / name
    if not p.exists():
        return None
    return json.loads(p.read_text())


def status():
    try:
        d = _load("schedule.json")
    except Exception as e:
        return {"state": "error", "message": f"schedule.json has a mistake: {e}"}
    if d is None:
        return {"state": "error", "message": f"Put a schedule.json file in {drop_folder()} (see the README)."}
    return {"state": "connected", "account": f"Schedule file ({len(d.get('events', []))} events)"}


def connect():
    return status()


def events(day=None):
    day = day or datetime.now().date()
    d = _load("schedule.json") or {}
    out = []
    for i, e in enumerate(d.get("events", [])):
        on = e.get("date") == day.isoformat() or (e.get("day") or "").lower()[:3] == DAYS[day.weekday()]
        if on:
            out.append({"id": f"f{i}", "subject": e["title"], "start": f"{day.isoformat()}T{e['start']}",
                        "end": f"{day.isoformat()}T{e['end']}", "location": e.get("location", ""),
                        "attendees": [], "online": False})
    out.sort(key=lambda e: e["start"])
    return out


def create_event(subject, start, end):
    p = drop_folder() / "schedule.json"
    d = json.loads(p.read_text()) if p.exists() else {"events": []}
    d.setdefault("events", []).append({"title": subject, "date": start[:10], "start": start[11:16], "end": end[11:16]})
    p.write_text(json.dumps(d, indent=2))
    return {"ok": True}


def _ts(hours=0, days=0):
    return (datetime.now(timezone.utc) - timedelta(hours=hours, days=days)).isoformat()


def sync_mail(days=3):
    d = _load("demo_mail.json") or {}
    rows = [(f"demo-in-{i}", f"subj:{e['subject'].lower()}", e["subject"], e.get("from_name", ""),
             e.get("from_email", "").lower(), _ts(hours=e.get("hours_ago", 2)), e.get("body", "")[:600], 0)
            for i, e in enumerate(d.get("emails", []))]
    db.many("""INSERT INTO emails(id,conversation_id,subject,sender_name,sender_email,received,preview,is_read)
               VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET is_read=excluded.is_read""", rows)
    srows = [(f"demo-out-{i}", f"subj:{e['subject'].lower()}", e["subject"], e.get("to_name", ""),
              e.get("to_email", "").lower(), _ts(days=e.get("days_ago", 5)), e.get("body", "")[:600])
             for i, e in enumerate(d.get("sent", []))]
    db.many("""INSERT OR IGNORE INTO sent(id,conversation_id,subject,to_name,to_email,sent,preview)
               VALUES(?,?,?,?,?,?,?)""", srows)
    return len(rows), len(srows)
