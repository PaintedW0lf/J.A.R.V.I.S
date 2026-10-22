"""IBM connector: SuccessFactors Goals, MyScore and YourLearning.

Phase A (now): drop files into the IBM drop folder. Supported:
  .pdf  (e.g. "Print to PDF" on the Goals page)
  .html / .htm / .mhtml  (File > Save Page As, "Webpage, HTML only")
  .txt  (select all on the page, copy, paste into a text file)
  .csv / .xlsx  (any export)
  .json (output of the Jarvis browser extension, phase B)
Name files with goals / myscore / learning / queue to make detection certain,
otherwise Jarvis guesses from the content.

Phase B (later, once permitted): the browser extension POSTs the same JSON
to /api/ibm/import, so nothing else in Jarvis changes.
"""
import csv
import json
import re
from datetime import datetime, date
from pathlib import Path

from . import ai, db
from .config import drop_folder

SOURCES = ("goals", "myscore", "learning")
SUPPORTED = {".pdf", ".html", ".htm", ".mhtml", ".txt", ".csv", ".xlsx", ".json"}
GOAL_STATUSES = ["Not Started", "In Progress", "On Hold", "Completed", "Cancelled", "Behind", "On Track"]
SCORE_STATUSES = ["Not Met", "Met", "Not Applicable", "In Progress"]


# ---------- read files into text ----------
def read_text(path: Path) -> str:
    ext = path.suffix.lower()
    if ext == ".pdf":
        from pypdf import PdfReader
        return "\n".join((p.extract_text() or "") for p in PdfReader(str(path)).pages)
    if ext in (".html", ".htm", ".mhtml"):
        from bs4 import BeautifulSoup
        raw = path.read_text(errors="ignore")
        if ext == ".mhtml":
            import quopri
            raw = quopri.decodestring(raw.encode()).decode("utf-8", "ignore")
        soup = BeautifulSoup(raw, "html.parser")
        for t in soup(["script", "style", "noscript", "svg"]):
            t.decompose()
        return soup.get_text("\n")
    if ext == ".xlsx":
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        lines = []
        for ws in wb.worksheets:
            for row in ws.iter_rows(values_only=True):
                lines.append(" | ".join("" if v is None else str(v) for v in row))
        return "\n".join(lines)
    return path.read_text(errors="ignore")


def clean_lines(text):
    out = []
    for ln in text.splitlines():
        ln = re.sub(r"\s+", " ", ln).strip(" \t•·")
        if ln and ln not in ("...", "•••"):
            out.append(ln)
    return out


def detect_source(path: Path, text: str):
    n = path.name.lower()
    for key, src in (("myscore", "myscore"), ("score", "myscore"), ("queue", "learning"),
                     ("learning", "learning"), ("course", "learning"), ("goal", "goals")):
        if key in n:
            return src
    t = text.lower()
    scores = {
        "myscore": t.count("not met") * 3 + t.count("not applicable") * 2 + t.count("myscore") * 5,
        "goals": t.count("due date:") * 2 + t.count("goal plan") * 5 + t.count("business outcomes") * 3,
        "learning": t.count("yourlearning") * 3 + t.count("queue") * 2 + t.count("course") + t.count("minutes"),
    }
    return max(scores, key=scores.get)


# ---------- dates ----------
def parse_date(s):
    if not s:
        return None
    s = s.strip().rstrip(".")
    m = re.search(r"due in (\d+) days?", s, re.I)
    if m:
        return date.fromordinal(date.today().toordinal() + int(m.group(1))).isoformat()
    for fmt in ("%b %d, %Y", "%B %d, %Y", "%Y-%m-%d", "%m/%d/%Y", "%d %b %Y", "%d-%b-%Y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            pass
    return None


# ---------- heuristic parsers (work without AI) ----------
def parse_goals(lines):
    items, section = [], ""
    sections = {"business outcomes", "skills", "development", "growth", "behaviors", "client", "personal"}
    i = 0
    while i < len(lines):
        ln = lines[i]
        if ln.lower() in sections or (len(ln) < 40 and ln.lower().rstrip(":") in sections):
            section = ln.rstrip(":")
        due_m = re.match(r"(?:Due Date:\s*(.+)|(Due in \d+ Days?))$", ln, re.I)
        if due_m:
            # title = preceding lines up to previous item boundary
            j, title_parts = i - 1, []
            while j >= 0 and len(title_parts) < 3:
                prev = lines[j]
                if (prev in GOAL_STATUSES or re.match(r"Due (Date|in)", prev, re.I)
                        or prev.lower() in sections or re.match(r"^\d+$", prev)):
                    break
                title_parts.insert(0, prev)
                j -= 1
            status = next((lines[k] for k in range(i + 1, min(i + 4, len(lines))) if lines[k] in GOAL_STATUSES), "")
            title = " ".join(title_parts).strip()
            if title:
                items.append({"title": title, "due": parse_date(due_m.group(1) or due_m.group(2)),
                              "status": status or "Unknown", "section": section})
        i += 1
    return items


def parse_myscore(lines):
    items = []
    skip = {"met", "not met", "not applicable", "terms of use", "help", "myscore"}
    for i, ln in enumerate(lines):
        if ln in SCORE_STATUSES:
            j = i - 1
            detail = []
            while j >= 0 and (lines[j].startswith(("Current:", "Expected:")) or lines[j].startswith("Completion")
                               or re.search(r"only$", lines[j]) or lines[j] in ("Required Learning",)):
                detail.insert(0, lines[j])
                j -= 1
            if j >= 0 and lines[j].lower() not in skip and lines[j] not in SCORE_STATUSES:
                items.append({"title": lines[j], "status": ln, "detail": "; ".join(detail), "section": "Yearly credential"})
    return items


def parse_learning(lines):
    items = []
    for i, ln in enumerate(lines):
        m = re.search(r"(?:due|complete by|due date)[:\s]+(.+)$", ln, re.I)
        status = next((s for s in ("In progress", "Not started", "Completed", "Enrolled", "Registered")
                       if s.lower() in ln.lower()), None)
        if (m or status) and i > 0 and len(lines[i - 1]) > 6:
            title = lines[i - 1]
            if not any(it["title"] == title for it in items):
                items.append({"title": title, "due": parse_date(m.group(1)) if m else None,
                              "status": status or "In queue", "section": "Learning queue"})
    return items


AI_SCHEMA = """Return {"items":[{"title":str,"status":str,"due":"YYYY-MM-DD" or null,"section":str,"detail":str}]}.
status must be one of: Not Started, In Progress, On Hold, Completed, Met, Not Met, Not Applicable, In queue.
Ignore navigation, footers, buttons and help text. Only include real goals, credentials or courses."""

AI_HINT = {
    "goals": "This is an IBM SuccessFactors goal plan. Sections are like 'Business Outcomes' and 'Skills'.",
    "myscore": "This is IBM MyScore: yearly credential requirements, each Met / Not Met / Not Applicable, sometimes with Current and Expected levels.",
    "learning": "This is IBM YourLearning: courses in progress or in the learning queue, with due dates or durations.",
}


def extract(source, text):
    lines = clean_lines(text)
    if ai.configured():
        try:
            data = ai.complete_json(
                "You extract structured records from IBM employee portal pages. " + AI_HINT[source] + "\n" + AI_SCHEMA,
                f"Today is {date.today().isoformat()}.\n\nPage text:\n" + "\n".join(lines)[:30000])
            items = data["items"] if isinstance(data, dict) else data
            if items:
                return items, "read with AI"
        except Exception as e:
            db.log("ibm", f"AI extraction failed, using built-in parser: {e}")
    parser = {"goals": parse_goals, "myscore": parse_myscore, "learning": parse_learning}[source]
    return parser(lines), "read with built-in parser"


# ---------- storing ----------
def replace_items(source, items, origin):
    db.x("DELETE FROM ibm_items WHERE source=? AND origin=?", (source, origin))
    db.many("""INSERT INTO ibm_items(source,title,status,due,section,detail,origin,updated)
               VALUES(?,?,?,?,?,?,?,?)""",
            [(source, it.get("title", "")[:200], it.get("status") or "", it.get("due"),
              it.get("section") or "", it.get("detail") or "", origin, db.now_iso()) for it in items if it.get("title")])


def import_file(path: Path):
    if path.suffix.lower() == ".json":
        payload = json.loads(path.read_text())
        return import_payload(payload, origin=path.name)
    text = read_text(path)
    if path.suffix.lower() == ".csv":
        rows = list(csv.DictReader(text.splitlines()))
        if rows and any(k and k.lower() in ("title", "name", "goal") for k in rows[0]):
            src = detect_source(path, text)
            items = [{"title": r.get("title") or r.get("name") or r.get("goal") or r.get("Title") or r.get("Name"),
                      "status": r.get("status") or r.get("Status") or "",
                      "due": parse_date(r.get("due") or r.get("Due") or r.get("Due Date") or ""),
                      "section": r.get("section") or r.get("Category") or ""} for r in rows]
            replace_items(src, items, path.name)
            return src, len(items), "read as table"
    src = detect_source(path, text)
    items, how = extract(src, text)
    replace_items(src, items, path.name)
    return src, len(items), how


def import_payload(payload, origin="extension"):
    """JSON from the browser extension or a .json file: {"source": "goals", "items": [...]}"""
    src = payload.get("source")
    if src not in SOURCES:
        raise ValueError("source must be goals, myscore or learning")
    items = payload.get("items") or []
    for it in items:
        it["due"] = parse_date(it.get("due")) or it.get("due")
    replace_items(src, items, origin)
    db.log("ibm", f"Imported {len(items)} {src} items from {origin}")
    return src, len(items), "imported"


def scan():
    """Import new or changed files from the drop folder."""
    folder = drop_folder()
    known = {r["path"]: r["mtime"] for r in db.q("SELECT path, mtime FROM ibm_files")}
    results = []
    for p in sorted(folder.iterdir()):
        if p.suffix.lower() not in SUPPORTED or p.name.startswith("."):
            continue
        mt = p.stat().st_mtime
        if known.get(str(p)) == mt:
            continue
        try:
            src, n, how = import_file(p)
            note = f"{n} items, {how}"
        except Exception as e:
            src, n, note = "", 0, f"Couldn't read this file: {e}"
        db.x("""INSERT INTO ibm_files(path,mtime,source,items,note,updated) VALUES(?,?,?,?,?,?)
                ON CONFLICT(path) DO UPDATE SET mtime=excluded.mtime, source=excluded.source,
                items=excluded.items, note=excluded.note, updated=excluded.updated""",
             (str(p), mt, src, n, note, db.now_iso()))
        db.log("ibm", f"{p.name}: {note}")
        results.append({"file": p.name, "source": src, "items": n, "note": note})
    # forget items whose file was deleted
    for path in set(known) - {str(p) for p in folder.iterdir()}:
        db.x("DELETE FROM ibm_items WHERE origin=?", (Path(path).name,))
        db.x("DELETE FROM ibm_files WHERE path=?", (path,))
    return results


def items(source=None):
    if source:
        return db.q("SELECT * FROM ibm_items WHERE source=? ORDER BY due IS NULL, due", (source,))
    return db.q("SELECT * FROM ibm_items ORDER BY source, due IS NULL, due")


def files():
    return db.q("SELECT * FROM ibm_files ORDER BY updated DESC")


DONE = {"completed", "met", "not applicable", "cancelled"}


def open_items():
    """Things still to do, soonest first, with days left."""
    out = []
    today = date.today()
    for it in items():
        if (it["status"] or "").lower() in DONE:
            continue
        days = None
        if it["due"]:
            try:
                days = (date.fromisoformat(it["due"]) - today).days
            except ValueError:
                pass
        it["days_left"] = days
        out.append(it)
    out.sort(key=lambda i: (i["days_left"] is None, i["days_left"] if i["days_left"] is not None else 0))
    return out
