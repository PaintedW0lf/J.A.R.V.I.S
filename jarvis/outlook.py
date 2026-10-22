"""Outlook / Microsoft 365 connector over Microsoft Graph.

Sign-in uses the device-code flow: Jarvis shows a short code, you open
microsoft.com/devicelogin, sign in with your @ibm.com account (w3id / MFA as usual)
and Jarvis gets a token. Nothing to host, no redirect URL, no client secret.
Tokens are cached in ~/.jarvis/msal_cache.bin (owner-only).
"""
import os
import threading
from datetime import datetime, timedelta, timezone

import httpx
import msal

from . import db
from .config import HOME, settings

GRAPH = "https://graph.microsoft.com/v1.0"
SCOPES = ["Mail.ReadWrite", "Mail.Send", "Calendars.ReadWrite", "User.Read"]
CACHE_FILE = HOME / "msal_cache.bin"

_flow = {}          # in-progress device flow
_lock = threading.Lock()


def _cache():
    c = msal.SerializableTokenCache()
    if CACHE_FILE.exists():
        c.deserialize(CACHE_FILE.read_text())
    return c


def _save(c):
    if c.has_state_changed:
        CACHE_FILE.write_text(c.serialize())
        os.chmod(CACHE_FILE, 0o600)


def _app(cache):
    o = settings()["outlook"]
    if not o.get("client_id"):
        raise RuntimeError("Add your Outlook app's client ID in Settings first.")
    return msal.PublicClientApplication(
        o["client_id"], authority=f"https://login.microsoftonline.com/{o.get('tenant') or 'organizations'}",
        token_cache=cache)


def token():
    cache = _cache()
    app = _app(cache)
    accts = app.get_accounts()
    if not accts:
        return None
    res = app.acquire_token_silent(SCOPES, account=accts[0])
    _save(cache)
    return res.get("access_token") if res else None


def g_status():
    o = settings()["outlook"]
    if not o.get("client_id"):
        return {"state": "needs_app", "message": "Add your app's client ID to connect Outlook."}
    if _flow.get("pending"):
        return {"state": "pending", "user_code": _flow["user_code"], "url": _flow["url"],
                "message": _flow.get("message")}
    try:
        cache = _cache()
        accts = _app(cache).get_accounts()
        if accts and token():
            return {"state": "connected", "account": accts[0].get("username")}
    except Exception as e:
        return {"state": "error", "message": str(e)}
    if _flow.get("error"):
        return {"state": "error", "message": _flow["error"]}
    return {"state": "signed_out"}


def g_start_sign_in():
    """Begin device-code sign-in. Returns the code to show the user."""
    with _lock:
        cache = _cache()
        app = _app(cache)
        flow = app.initiate_device_flow(scopes=SCOPES)
        if "user_code" not in flow:
            err = flow.get("error_description") or str(flow)
            if "AADSTS65001" in err or "consent" in err.lower():
                err = "Your organization needs to approve this app (admin consent). See the README section on IBM IT approval."
            raise RuntimeError(err)
        _flow.clear()
        _flow.update(pending=True, user_code=flow["user_code"], url=flow["verification_uri"],
                     message=flow.get("message"))

    def wait():
        res = app.acquire_token_by_device_flow(flow)  # blocks until done or expired
        _save(cache)
        _flow["pending"] = False
        if "access_token" in res:
            db.log("outlook", "Signed in to Outlook")
        else:
            d = res.get("error_description", "Sign-in didn't finish.")
            if "AADSTS65001" in d or "AADSTS90094" in d or "admin" in d.lower():
                d = "IBM needs to approve this app before it can read your mail (admin consent required)."
            _flow["error"] = d
    threading.Thread(target=wait, daemon=True).start()
    return {"user_code": _flow["user_code"], "url": _flow["url"]}


def g_sign_out():
    if CACHE_FILE.exists():
        CACHE_FILE.unlink()
    _flow.clear()


def _get(path, params=None):
    t = token()
    if not t:
        raise RuntimeError("Outlook isn't connected.")
    r = httpx.get(GRAPH + path, params=params, headers={"Authorization": f"Bearer {t}",
                  "Prefer": 'outlook.body-content-type="text"'}, timeout=30)
    r.raise_for_status()
    return r.json()


def _post(path, body):
    t = token()
    if not t:
        raise RuntimeError("Outlook isn't connected.")
    r = httpx.post(GRAPH + path, json=body, headers={"Authorization": f"Bearer {t}"}, timeout=30)
    r.raise_for_status()
    return r.json() if r.content else {}


# ---------- sync ----------
def g_sync_mail(days=3):
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    sel = "id,conversationId,subject,from,receivedDateTime,bodyPreview,isRead"
    inbox = _get("/me/mailFolders/inbox/messages", {"$filter": f"receivedDateTime ge {since}",
                 "$select": sel, "$orderby": "receivedDateTime desc", "$top": "100"})["value"]
    rows = [(m["id"], m.get("conversationId"), m.get("subject") or "(no subject)",
             m.get("from", {}).get("emailAddress", {}).get("name", ""),
             m.get("from", {}).get("emailAddress", {}).get("address", "").lower(),
             m["receivedDateTime"], m.get("bodyPreview", "")[:600], int(m.get("isRead", False)))
            for m in inbox]
    db.many("""INSERT INTO emails(id,conversation_id,subject,sender_name,sender_email,received,preview,is_read)
               VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET is_read=excluded.is_read""", rows)

    sent_since = (datetime.now(timezone.utc) - timedelta(days=14)).strftime("%Y-%m-%dT%H:%M:%SZ")
    sent = _get("/me/mailFolders/sentitems/messages", {"$filter": f"sentDateTime ge {sent_since}",
                "$select": "id,conversationId,subject,toRecipients,sentDateTime,bodyPreview",
                "$orderby": "sentDateTime desc", "$top": "100"})["value"]
    srows = []
    for m in sent:
        to = (m.get("toRecipients") or [{}])[0].get("emailAddress", {})
        srows.append((m["id"], m.get("conversationId"), m.get("subject") or "", to.get("name", ""),
                      to.get("address", "").lower(), m["sentDateTime"], m.get("bodyPreview", "")[:600]))
    db.many("""INSERT OR IGNORE INTO sent(id,conversation_id,subject,to_name,to_email,sent,preview)
               VALUES(?,?,?,?,?,?,?)""", srows)
    return len(rows), len(srows)


def g_events(day=None):
    tz = settings()["timezone"]
    day = day or datetime.now().date()
    # include the local UTC offset, otherwise Graph treats the times as UTC
    start = datetime.combine(day, datetime.min.time()).astimezone().isoformat()
    end = datetime.combine(day, datetime.max.time()).astimezone().isoformat(timespec="seconds")
    t = token()
    if not t:
        raise RuntimeError("Outlook isn't connected.")
    r = httpx.get(GRAPH + "/me/calendarView", params={"startDateTime": start, "endDateTime": end,
                  "$select": "id,subject,start,end,location,attendees,isOnlineMeeting,showAs",
                  "$orderby": "start/dateTime", "$top": "50"},
                  headers={"Authorization": f"Bearer {t}", "Prefer": f'outlook.timezone="{tz}"'}, timeout=30)
    r.raise_for_status()
    out = []
    for e in r.json()["value"]:
        if e.get("showAs") == "free":
            continue
        out.append({"id": e["id"], "subject": e.get("subject") or "(busy)",
                    "start": e["start"]["dateTime"][:16], "end": e["end"]["dateTime"][:16],
                    "location": (e.get("location") or {}).get("displayName", ""),
                    "attendees": [a["emailAddress"].get("name") for a in e.get("attendees", [])][:6],
                    "online": e.get("isOnlineMeeting", False)})
    return out


def g_create_reply_draft(message_id, body, reply_all=False):
    """Creates a reply draft inside Outlook (shows up in your Drafts folder)."""
    d = _post(f"/me/messages/{message_id}/{'createReplyAll' if reply_all else 'createReply'}", {})
    t = token()
    httpx.patch(GRAPH + f"/me/messages/{d['id']}", json={"body": {"contentType": "Text", "content": body}},
                headers={"Authorization": f"Bearer {t}"}, timeout=30).raise_for_status()
    return d["id"]


def g_send_draft(draft_id):
    _post(f"/me/messages/{draft_id}/send", {})


def g_send_mail(to, subject, body):
    _post("/me/sendMail", {"message": {"subject": subject, "body": {"contentType": "Text", "content": body},
                                       "toRecipients": [{"emailAddress": {"address": to}}]}, "saveToSentItems": True})


def g_create_event(subject, start, end):
    tz = settings()["timezone"]
    return _post("/me/events", {"subject": subject, "start": {"dateTime": start, "timeZone": tz},
                                "end": {"dateTime": end, "timeZone": tz}, "showAs": "busy"})


# ---------- mode switch: "mac" (Outlook app on this Mac, no registration) or "graph" (Microsoft Graph) ----------
import json as _json
from . import outlook_mac as mac
from . import outlook_file as fil


def mode():
    return settings()["outlook"].get("mode", "mac")


def status():
    st = mac.status() if mode() == "mac" else fil.status() if mode() == "file" else g_status()
    st["mode"] = mode()
    return st


def start_sign_in():
    return mac.connect() if mode() == "mac" else fil.connect() if mode() == "file" else g_start_sign_in()


def sign_out():
    if mode() == "graph":
        g_sign_out()


def sync_mail(days=3):
    return mac.sync_mail(days) if mode() == "mac" else fil.sync_mail(days) if mode() == "file" else g_sync_mail(days)


def events(day=None):
    return mac.events(day) if mode() == "mac" else fil.events(day) if mode() == "file" else g_events(day)


def create_reply_draft(message_id, body, reply_all=False):
    if mode() in ("mac", "file"):   # nothing is created yet: the reply is made when you send or open it
        return _json.dumps({"mac": 1, "id": message_id, "body": body, "all": reply_all})
    return g_create_reply_draft(message_id, body, reply_all)


def send_draft(draft_id):
    if mode() == "file":
        return   # file mode never sends anything
    if mode() == "mac":
        d = _json.loads(draft_id)
        mac.reply(d["id"], d["body"], d["all"], send=True)
    else:
        g_send_draft(draft_id)


def open_draft(draft_id):
    """'Save to Outlook drafts': in Mac mode this opens the reply window in Outlook for you to finish."""
    if mode() == "mac":
        d = _json.loads(draft_id)
        mac.reply(d["id"], d["body"], d["all"], send=False)


def send_mail(to, subject, body):
    if mode() == "file":
        return
    return mac.send_mail(to, subject, body) if mode() == "mac" else g_send_mail(to, subject, body)


def create_event(subject, start, end):
    return mac.create_event(subject, start, end) if mode() == "mac" else fil.create_event(subject, start, end) if mode() == "file" else g_create_event(subject, start, end)


def my_address():
    if mode() == "mac":
        return settings().get("email") or None
    return _get("/me").get("mail")
