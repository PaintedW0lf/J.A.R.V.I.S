"""Personal Gmail mode: no Google Cloud project, no admin approval.

Mail: Gmail over IMAP (reading) and SMTP (sending), using a Google *App Password*.
Calendar (optional): your Google Calendar "secret address in iCal format" URL, read-only.
Time blocks you approve are saved to schedule.json in the drop folder (Jarvis shows them
alongside your Google events); they are not written into Google Calendar.

Nothing is sent unless you press "Approve and send". "Save to Outlook drafts" saves a real
draft into your Gmail Drafts folder instead.
"""
import email
import imaplib
import re
import smtplib
import ssl
import time
from datetime import datetime, timedelta, timezone
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.utils import parseaddr, parsedate_to_datetime

import httpx

from . import db, outlook_file as fil
from .config import get_secret, settings

IMAP_HOST, SMTP_HOST = "imap.gmail.com", "smtp.gmail.com"


class GmailError(Exception):
    pass


def _addr():
    return (settings().get("gmail", {}).get("address") or "").strip()


def _pw():
    return re.sub(r"\s+", "", get_secret("gmail_app_password") or "")


def _imap():
    if not _addr() or not _pw():
        raise GmailError("Add your Gmail address and App Password in Settings.")
    try:
        m = imaplib.IMAP4_SSL(IMAP_HOST, timeout=30)
        m.login(_addr(), _pw())
        return m
    except imaplib.IMAP4.error as e:
        msg = e.args[0].decode() if e.args and isinstance(e.args[0], bytes) else str(e)
        if "IMAP" in msg.upper() and "disabled" in msg.lower():
            raise GmailError("IMAP is turned off in Gmail. In Gmail go to Settings, See all settings, "
                             "Forwarding and POP/IMAP, and enable IMAP.")
        raise GmailError("Google rejected the sign-in. Use an App Password (16 letters), not your normal "
                         "Google password, and check the address. App Passwords need 2-Step Verification on.")
    except OSError as e:
        raise GmailError(f"Couldn't reach Gmail: {e}")


_cache = {"t": 0, "val": None}


def status():
    if time.time() - _cache["t"] < 60 and _cache["val"]:
        return _cache["val"]
    try:
        m = _imap()
        _, d = m.select("INBOX", readonly=True)
        n = int(d[0])
        m.logout()
        cal = "with calendar" if get_secret("gmail_ical_url") else "no calendar link yet"
        val = {"state": "connected", "account": f"Gmail {_addr()} ({n} in Inbox, {cal})"}
    except GmailError as e:
        val = {"state": "error", "message": str(e)}
    _cache.update(t=time.time(), val=val)
    return val


def connect():
    _cache["t"] = 0
    return status()


# ---------- parsing ----------
def _h(v):
    try:
        return str(make_header(decode_header(v or "")))
    except Exception:
        return v or ""


def _text(msg):
    plain, html = "", ""
    for part in msg.walk():
        if part.get_content_maintype() != "text" or part.get_filename():
            continue
        try:
            body = part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "replace")
        except Exception:
            continue
        if part.get_content_subtype() == "plain" and not plain:
            plain = body
        elif part.get_content_subtype() == "html" and not html:
            html = body
    if not plain and html:
        from bs4 import BeautifulSoup
        plain = BeautifulSoup(html, "html.parser").get_text(" ")
    plain = re.split(r"\n>|\nOn .{5,80} wrote:", plain)[0]   # drop the quoted history
    return re.sub(r"\s+", " ", plain).strip()


def _fetch(m, folder, days, limit=60):
    st, _ = m.select(f'"{folder}"', readonly=True)
    if st != "OK":
        return []
    since = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")
    _, ids = m.search(None, "SINCE", since)
    nums = ids[0].split()[-limit:]
    out = []
    for n in nums:
        _, data = m.fetch(n, "(X-GM-THRID X-GM-MSGID FLAGS BODY.PEEK[])")
        for item in data:
            if not isinstance(item, tuple):
                continue
            meta = item[0].decode(errors="ignore")
            thr = re.search(r"X-GM-THRID (\d+)", meta)
            mid = re.search(r"X-GM-MSGID (\d+)", meta)
            msg = email.message_from_bytes(item[1])
            try:
                when = parsedate_to_datetime(msg["Date"]).astimezone(timezone.utc).isoformat()
            except Exception:
                when = datetime.now(timezone.utc).isoformat()
            out.append({"thr": thr.group(1) if thr else "", "mid": mid.group(1) if mid else n.decode(),
                        "seen": "\\Seen" in meta, "when": when, "msg": msg})
    return out


def sync_mail(days=3):
    m = _imap()
    try:
        ins = _fetch(m, "INBOX", days)
        outs = _fetch(m, "[Gmail]/Sent Mail", 14, limit=40)
    finally:
        try:
            m.logout()
        except Exception:
            pass
    rows = []
    for r in ins:
        name, addr = parseaddr(_h(r["msg"]["From"]))
        rows.append((f"g-{r['mid']}", f"gt-{r['thr']}", _h(r["msg"]["Subject"]) or "(no subject)", name or addr,
                     addr.lower(), r["when"], _text(r["msg"])[:600], 1 if r["seen"] else 0))
    db.many("""INSERT INTO emails(id,conversation_id,subject,sender_name,sender_email,received,preview,is_read)
               VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET is_read=excluded.is_read""", rows)
    srows = []
    for r in outs:
        name, addr = parseaddr(_h(r["msg"]["To"]).split(",")[0])
        srows.append((f"gs-{r['mid']}", f"gt-{r['thr']}", _h(r["msg"]["Subject"]) or "(no subject)", name or addr,
                      addr.lower(), r["when"], _text(r["msg"])[:600]))
    db.many("""INSERT OR IGNORE INTO sent(id,conversation_id,subject,to_name,to_email,sent,preview)
               VALUES(?,?,?,?,?,?,?)""", srows)
    return len(rows), len(srows)


# ---------- calendar (read-only iCal link + local blocks) ----------
def events(day=None):
    day = day or datetime.now().date()
    out = list(fil.events(day))          # blocks you approved in Jarvis
    url = get_secret("gmail_ical_url")
    if url:
        try:
            import icalendar
            import recurring_ical_events
            r = httpx.get(url, timeout=20, follow_redirects=True)
            r.raise_for_status()
            cal = icalendar.Calendar.from_ical(r.content)
            for i, e in enumerate(recurring_ical_events.of(cal).at(day)):
                s, en = e.decoded("DTSTART"), e.decoded("DTEND") if e.get("DTEND") else None
                if not isinstance(s, datetime):
                    continue                      # skip all-day items
                s = s.astimezone().replace(tzinfo=None) if s.tzinfo else s
                en = (en.astimezone().replace(tzinfo=None) if en.tzinfo else en) if en else s + timedelta(hours=1)
                out.append({"id": f"gc{i}", "subject": str(e.get("SUMMARY", "(busy)")), "start": s.strftime("%Y-%m-%dT%H:%M"),
                            "end": en.strftime("%Y-%m-%dT%H:%M"), "location": str(e.get("LOCATION", "")),
                            "attendees": [], "online": False})
        except Exception as ex:
            db.log("calendar", f"Google Calendar link failed: {ex}")
    out.sort(key=lambda e: e["start"])
    return out


def create_event(subject, start, end):
    return fil.create_event(subject, start, end)


# ---------- sending / drafts ----------
def _build(to, subject, body, in_reply_to=None):
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = _addr(), to, subject
    if in_reply_to:
        msg["In-Reply-To"] = msg["References"] = in_reply_to
    msg.set_content(body)
    return msg


def _target(message_id, reply_all):
    """Who to write to, and the subject, for a stored inbox email (or a sent one for a nudge)."""
    if message_id.startswith("gs-"):
        r = db.q("SELECT * FROM sent WHERE id=?", (message_id,))
        if not r:
            raise GmailError("I can't find that message any more.")
        return r[0]["to_email"], r[0]["subject"]
    r = db.q("SELECT * FROM emails WHERE id=?", (message_id,))
    if not r:
        raise GmailError("I can't find that message any more.")
    return r[0]["sender_email"], r[0]["subject"]


def _msgid_header(m, message_id):
    try:
        folder = "[Gmail]/Sent Mail" if message_id.startswith("gs-") else "INBOX"
        m.select(f'"{folder}"', readonly=True)
        _, f = m.search(None, "X-GM-MSGID", message_id.split("-", 1)[1])
        if f[0]:
            _, d = m.fetch(f[0].split()[0], "(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)])")
            return email.message_from_bytes(d[0][1]).get("Message-ID")
    except Exception:
        pass
    return None


def reply(message_id, body, reply_all=False, send=True):
    to, subject = _target(message_id, reply_all)
    subject = subject if subject.lower().startswith("re:") else "RE: " + subject
    m = _imap()
    try:
        msg = _build(to, subject, body, _msgid_header(m, message_id))
        if send:
            ctx = ssl.create_default_context()
            with smtplib.SMTP_SSL(SMTP_HOST, 465, context=ctx, timeout=30) as s:
                s.login(_addr(), _pw())
                s.send_message(msg)
        else:
            m.append('"[Gmail]/Drafts"', "\\Draft", imaplib.Time2Internaldate(time.time()), msg.as_bytes())
    finally:
        try:
            m.logout()
        except Exception:
            pass


def send_mail(to, subject, body):
    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL(SMTP_HOST, 465, context=ctx, timeout=30) as s:
        s.login(_addr(), _pw())
        s.send_message(_build(to, subject, body))


if __name__ == "__main__":
    print(status())
