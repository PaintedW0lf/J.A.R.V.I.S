"""Jarvis local server: http://localhost:8765

Binds to 127.0.0.1 only, so nothing on your network can reach it.
"""
import shutil
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from . import agents, ai, db, ibm, outlook
from .config import drop_folder, has_secret, save_settings, set_secret, settings

ROOT = Path(__file__).resolve().parent.parent
app = FastAPI(title="Jarvis")
# Only the local UI and the Jarvis browser extension may call the API.
app.add_middleware(CORSMiddleware, allow_origin_regex=r"^(http://(localhost|127\.0\.0\.1)(:\d+)?|chrome-extension://.*)$",
                   allow_methods=["*"], allow_headers=["*"])
scheduler = BackgroundScheduler()


@app.exception_handler(Exception)
async def errors(_req: Request, exc: Exception):
    return JSONResponse({"error": str(exc)}, status_code=400)


def schedule():
    scheduler.remove_all_jobs()
    hh, mm = settings()["brief_time"].split(":")
    scheduler.add_job(agents.brief_job, "cron", hour=int(hh), minute=int(mm), id="brief")
    scheduler.add_job(agents.sync_job, "interval", minutes=5, id="sync")


@app.on_event("startup")
def startup():
    db.init()
    drop_folder()
    schedule()
    scheduler.start()
    scheduler.add_job(agents.sync_job, id="first-sync")  # run once right away


@app.get("/")
def index():
    return FileResponse(ROOT / "web" / "index.html")


# ---------- settings ----------
class SettingsIn(BaseModel):
    patch: dict = {}
    ai_key: str | None = None


@app.get("/api/settings")
def get_settings():
    s = settings()
    return {**s, "ai_key_set": has_secret("ai_key"), "ai_ready": ai.configured(),
            "drop_folder_resolved": str(drop_folder())}


@app.post("/api/settings")
def post_settings(body: SettingsIn):
    if body.patch:
        save_settings(body.patch)
    where = None
    if body.ai_key is not None:
        where = set_secret("ai_key", body.ai_key.strip())
    if "brief_time" in body.patch:
        schedule()
    return {**get_settings(), "key_saved_in": where}


@app.post("/api/ai/test")
def ai_test():
    try:
        return {"ok": True, "reply": ai.test()}
    except ai.AIError as e:
        return {"ok": False, "error": str(e)}


# ---------- outlook ----------
@app.get("/api/outlook/status")
def o_status():
    return outlook.status()


@app.post("/api/outlook/connect")
def o_connect():
    return outlook.start_sign_in()


@app.post("/api/outlook/disconnect")
def o_disconnect():
    outlook.sign_out()
    return {"ok": True}


# ---------- dashboard ----------
@app.get("/api/state")
def state():
    g = agents.gather()
    return {
        "outlook": g["outlook"], "ai": g["ai"], "name": settings()["name"],
        "brief": agents.brief(),
        "needs": [{"id": e["id"], "who": e["sender_name"] or e["sender_email"], "subject": e["subject"],
                   "task": e["task"], "due": e["due"], "received": e["received"]} for e in g["needs"]],
        "waiting": [{"id": w["id"], "who": w["to_name"] or w["to_email"], "subject": w["subject"], "days": w["days"]}
                    for w in g["waiting"]],
        "events": g["events"], "free": g["free"], "goals": g["goals"],
        "ibm_counts": {s: len(ibm.items(s)) for s in ibm.SOURCES},
    }


@app.post("/api/sync")
def sync():
    agents.sync_job()
    return {"ok": True}


@app.post("/api/brief/refresh")
def brief_refresh():
    return {"text": agents.brief(force=True)}


# ---------- chat + drafts ----------
class ChatIn(BaseModel):
    message: str
    history: list = []


@app.post("/api/chat")
def chat(body: ChatIn):
    return agents.chat(body.message, body.history)


class DraftIn(BaseModel):
    email_id: str | None = None
    sent_id: str | None = None
    instructions: str = ""


@app.post("/api/draft")
def draft(body: DraftIn):
    if body.email_id:
        return agents.draft_reply(body.email_id, body.instructions)
    if body.sent_id:
        return agents.draft_nudge(body.sent_id)
    raise HTTPException(400, "Say which email to draft for.")


class ApproveIn(BaseModel):
    body: str
    mode: str = "send"   # "send" or "save" (save to Outlook Drafts)


@app.post("/api/draft/{draft_id}/approve")
def approve(draft_id: int, body: ApproveIn):
    if body.mode == "save":
        agents.save_to_outlook_drafts(draft_id, body.body)
        return {"ok": True, "status": "saved"}
    agents.approve_draft(draft_id, body.body)
    return {"ok": True, "status": "sent"}


@app.post("/api/draft/{draft_id}/discard")
def discard(draft_id: int):
    db.x("UPDATE drafts SET status='discarded' WHERE id=?", (draft_id,))
    return {"ok": True}


class BlockIn(BaseModel):
    title: str
    start: str  # HH:MM today
    end: str


@app.post("/api/calendar/block")
def block(body: BlockIn):
    from datetime import date
    d = date.today().isoformat()
    outlook.create_event(body.title, f"{d}T{body.start}:00", f"{d}T{body.end}:00")
    db.log("calendar", f"Blocked {body.start}-{body.end}: {body.title}")
    return {"ok": True}


# ---------- IBM ----------
@app.get("/api/ibm")
def ibm_all():
    return {"items": ibm.items(), "files": ibm.files(), "folder": str(drop_folder())}


@app.post("/api/ibm/upload")
async def ibm_upload(file: UploadFile):
    name = Path(file.filename).name
    if Path(name).suffix.lower() not in ibm.SUPPORTED:
        raise HTTPException(400, "Use PDF, HTML, TXT, CSV, XLSX or JSON.")
    dest = drop_folder() / name
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    return {"results": ibm.scan()}


@app.post("/api/ibm/scan")
def ibm_scan():
    return {"results": ibm.scan()}


@app.post("/api/ibm/import")
def ibm_import(payload: dict):
    """Phase B: the browser extension posts {"source": "...", "items": [...]} here."""
    src, n, _ = ibm.import_payload(payload, origin="extension:" + payload.get("source", ""))
    return {"source": src, "items": n}


@app.get("/api/log")
def get_log():
    return db.q("SELECT * FROM log ORDER BY id DESC LIMIT 50")
