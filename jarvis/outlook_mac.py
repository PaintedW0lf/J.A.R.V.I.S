"""Outlook connector that talks to the Outlook app already on your Mac (AppleScript).

No Azure app, no client ID, no IBM admin approval: Jarvis asks the Outlook app you're
already signed into for your mail and calendar, the same way you'd click through it.
macOS shows a one-time "Terminal wants to control Microsoft Outlook" prompt; allow it
(System Settings > Privacy & Security > Automation lets you turn it off any time).

Needs an Outlook that supports AppleScript. If your Outlook is the "New Outlook"
and doesn't, status() says so plainly.

Note: the AppleScript calendar returns a repeating meeting as one entry on its first
date, so some recurring meetings may not appear on later days.
"""
import subprocess
import time
import uuid
from datetime import datetime, timedelta, timezone

from . import db

FS, RS = "\x1f", "\x1e"
_cache = {"t": 0, "val": None}

HELPERS = '''
on pad(n)
  return text -2 thru -1 of ("0" & n)
end pad
on iso(d)
  set secs to time of d
  return ((year of d) as text) & "-" & my pad((month of d) as integer) & "-" & my pad(day of d) & "T" & my pad(secs div 3600) & ":" & my pad((secs mod 3600) div 60) & ":00"
end iso
on mkdate(y, mo, dd, hh, mm)
  set d to current date
  set day of d to 1
  set year of d to y
  set month of d to mo
  set day of d to dd
  set time of d to (hh * 3600 + mm * 60)
  return d
end mkdate
'''


class MacOutlookError(RuntimeError):
    pass


def _run(script, args=(), timeout=90):
    try:
        p = subprocess.run(["osascript", "-"] + [str(a) for a in args], input=script, text=True,
                           capture_output=True, timeout=timeout)
    except FileNotFoundError:
        raise MacOutlookError("This connector only works on a Mac.")
    except subprocess.TimeoutExpired:
        raise MacOutlookError("Outlook took too long to answer. Open Outlook and try again.")
    if p.returncode != 0:
        err = (p.stderr or "").strip()
        low = err.lower()
        if "-1743" in err or "not authorized" in low or "not allowed" in low:
            raise MacOutlookError("macOS blocked Jarvis from controlling Outlook. Open System Settings > Privacy & Security > "
                                  "Automation, and switch on Microsoft Outlook under Terminal (or the app you start Jarvis from).")
        if "-1728" in err or "-2741" in err or "-1708" in err or "doesn't understand" in low or "syntax error" in low:
            raise MacOutlookError("This Outlook doesn't support being controlled by scripts (this is how the \"New Outlook\" behaves). "
                                  "Switch Outlook back to the classic version if your IBM setup allows it, or use the file-drop import instead.")
        if "application isn" in low or "-600" in err or "can't get application" in low:
            raise MacOutlookError("Microsoft Outlook isn't installed or can't be opened.")
        raise MacOutlookError(err or "Outlook didn't answer.")
    return p.stdout


def _local_to_utc(s):
    return datetime.fromisoformat(s).astimezone(timezone.utc).isoformat()


# ---------- status ----------
def status():
    if time.time() - _cache["t"] < 60 and _cache["val"]:
        return _cache["val"]
    try:
        out = _run('tell application "Microsoft Outlook" to return (count of messages of inbox) as text', timeout=45)
        val = {"state": "connected", "account": f"Outlook on this Mac ({out.strip()} messages in Inbox)"}
    except MacOutlookError as e:
        val = {"state": "error", "message": str(e)}
    _cache.update(t=time.time(), val=val)
    return val


def connect():
    _cache["t"] = 0
    return status()


# ---------- mail ----------
MAIL_SCRIPT = HELPERS + '''
on run argv
  set days_back to (item 1 of argv) as integer
  set folder_kind to item 2 of argv
  set FS to character id 31
  set RS to character id 30
  set out to ""
  tell application "Microsoft Outlook"
    set cutoff to (current date) - (days_back * days)
    if folder_kind is "inbox" then
      set msgs to (messages of inbox whose time received > cutoff)
    else
      set msgs to (messages of sent items whose time sent > cutoff)
    end if
    set n to 0
    repeat with m in msgs
      set n to n + 1
      if n > 120 then exit repeat
      try
        set pv to plain text content of m
        if (length of pv) > 600 then set pv to text 1 thru 600 of pv
        if folder_kind is "inbox" then
          set s to sender of m
          set nm to ""
          set ad to ""
          try
            set nm to name of s
          end try
          try
            set ad to address of s
          end try
          set out to out & (id of m as text) & FS & (subject of m) & FS & nm & FS & ad & FS & my iso(time received of m) & FS & pv & FS & (is read of m as text) & RS
        else
          set nm to ""
          set ad to ""
          try
            set r to item 1 of (to recipients of m)
            set nm to name of email address of r
            set ad to address of email address of r
          end try
          set out to out & (id of m as text) & FS & (subject of m) & FS & nm & FS & ad & FS & my iso(time sent of m) & FS & pv & RS
        end if
      end try
    end repeat
  end tell
  return out
end run
'''


def _parse(out):
    return [r.split(FS) for r in out.split(RS) if r.strip()]


def _conv(subject):
    s = (subject or "").lower().strip()
    while s.startswith(("re:", "fw:", "fwd:")):
        s = s.split(":", 1)[1].strip()
    return "subj:" + s


def sync_mail(days=3):
    rows = []
    for f in _parse(_run(MAIL_SCRIPT, (days, "inbox"), timeout=180)):
        if len(f) < 7:
            continue
        mid, subj, nm, ad, dt, pv, rd = f[:7]
        rows.append((mid, _conv(subj), subj or "(no subject)", nm, ad.lower(), _local_to_utc(dt), pv[:600],
                     int(rd.strip().lower() == "true")))
    db.many("""INSERT INTO emails(id,conversation_id,subject,sender_name,sender_email,received,preview,is_read)
               VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET is_read=excluded.is_read""", rows)
    srows = []
    for f in _parse(_run(MAIL_SCRIPT, (14, "sent"), timeout=180)):
        if len(f) < 6:
            continue
        mid, subj, nm, ad, dt, pv = f[:6]
        srows.append((mid, _conv(subj), subj, nm, ad.lower(), _local_to_utc(dt), pv[:600]))
    db.many("""INSERT OR IGNORE INTO sent(id,conversation_id,subject,to_name,to_email,sent,preview)
               VALUES(?,?,?,?,?,?,?)""", srows)
    return len(rows), len(srows)


# ---------- calendar ----------
EVENTS_SCRIPT = HELPERS + '''
on run argv
  set y to (item 1 of argv) as integer
  set mo to (item 2 of argv) as integer
  set dd to (item 3 of argv) as integer
  set FS to character id 31
  set RS to character id 30
  set out to ""
  set d0 to my mkdate(y, mo, dd, 0, 0)
  set d1 to d0 + (1 * days)
  tell application "Microsoft Outlook"
    set evs to (calendar events whose start time >= d0 and start time < d1)
    repeat with e in evs
      try
        if not (all day flag of e) then
          set loc to ""
          try
            set loc to location of e
          end try
          set out to out & (id of e as text) & FS & (subject of e) & FS & my iso(start time of e) & FS & my iso(end time of e) & FS & loc & RS
        end if
      end try
    end repeat
  end tell
  return out
end run
'''


def events(day=None):
    day = day or datetime.now().date()
    out = []
    for f in _parse(_run(EVENTS_SCRIPT, (day.year, day.month, day.day), timeout=90)):
        if len(f) < 5:
            continue
        eid, subj, st, en, loc = f[:5]
        out.append({"id": eid, "subject": subj or "(busy)", "start": st[:16], "end": en[:16],
                    "location": loc, "attendees": [], "online": False})
    out.sort(key=lambda e: e["start"])
    return out


EVENT_SCRIPT = HELPERS + '''
on run argv
  set subj to item 1 of argv
  set sd to my mkdate((item 2 of argv) as integer, (item 3 of argv) as integer, (item 4 of argv) as integer, (item 5 of argv) as integer, (item 6 of argv) as integer)
  set ed to my mkdate((item 2 of argv) as integer, (item 3 of argv) as integer, (item 4 of argv) as integer, (item 7 of argv) as integer, (item 8 of argv) as integer)
  tell application "Microsoft Outlook"
    make new calendar event with properties {subject:subj, start time:sd, end time:ed}
  end tell
  return "ok"
end run
'''


def create_event(subject, start, end):
    s, e = datetime.fromisoformat(start), datetime.fromisoformat(end)
    _run(EVENT_SCRIPT, (subject, s.year, s.month, s.day, s.hour, s.minute, e.hour, e.minute))
    return {"ok": True}


# ---------- reply / send ----------
REPLY_SCRIPT = '''
on run argv
  set mid to (item 1 of argv) as integer
  set bodyText to item 2 of argv
  set replyAll to (item 3 of argv) is "1"
  set doSend to (item 4 of argv) is "1"
  tell application "Microsoft Outlook"
    set m to message id mid
    if replyAll then
      set r to reply to m with reply to all
    else
      set r to reply to m
    end if
    set oldc to content of r
    set content of r to bodyText & return & return & oldc
    if doSend then
      send r
    else
      open r
    end if
  end tell
  return "ok"
end run
'''


def reply(message_id, body, reply_all=False, send=False):
    """send=False opens the reply in an Outlook window so you can look it over and send it yourself."""
    _run(REPLY_SCRIPT, (message_id, body, "1" if reply_all else "0", "1" if send else "0"))


SEND_SCRIPT = '''
on run argv
  tell application "Microsoft Outlook"
    set m to make new outgoing message with properties {subject:(item 2 of argv), content:(item 3 of argv)}
    make new recipient at m with properties {email address:{address:(item 1 of argv)}}
    send m
  end tell
  return "ok"
end run
'''


def send_mail(to, subject, body):
    _run(SEND_SCRIPT, (to, subject, body))


def my_address():
    return None


DIAG_SCRIPT = '''
on run argv
  set out to ""
  tell application "Microsoft Outlook"
    set out to out & "Outlook version: " & (version as text) & linefeed
    try
      set out to out & "Default inbox count: " & (count of messages of inbox) & linefeed
    on error e
      set out to out & "Default inbox error: " & e & linefeed
    end try
    try
      repeat with f in (every mail folder)
        try
          set out to out & "Folder: " & (name of f) & " = " & (count of messages of f) & linefeed
        end try
      end repeat
    on error e
      set out to out & "Folder list error: " & e & linefeed
    end try
    try
      set out to out & "Exchange accounts: " & (count of exchange accounts) & linefeed
    end try
  end tell
  return out
end run
'''


def diagnose():
    return _run(DIAG_SCRIPT, timeout=120)


if __name__ == "__main__":
    import sys
    if "--diagnose" in sys.argv:
        print(diagnose())
        raise SystemExit
    # Run:  python -m jarvis.outlook_mac     to check that Jarvis can reach your Outlook.
    print("Checking Outlook on this Mac...")
    s = status()
    print(s["account"] if s["state"] == "connected" else "PROBLEM: " + s["message"])
    if s["state"] == "connected":
        try:
            n = len(events())
            print(f"Calendar OK: {n} meeting(s) found today.")
        except MacOutlookError as e:
            print("Calendar problem:", e)
