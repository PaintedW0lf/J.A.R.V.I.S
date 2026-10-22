"""Local SQLite store. Everything Jarvis knows stays in ~/.jarvis/jarvis.db."""
import sqlite3
import threading
from datetime import datetime, timezone

from .config import HOME

DB_PATH = HOME / "jarvis.db"
_lock = threading.RLock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS emails(
  id TEXT PRIMARY KEY, conversation_id TEXT, subject TEXT, sender_name TEXT, sender_email TEXT,
  received TEXT, preview TEXT, is_read INTEGER, category TEXT, reason TEXT, due TEXT,
  task TEXT, triaged INTEGER DEFAULT 0, handled INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS sent(
  id TEXT PRIMARY KEY, conversation_id TEXT, subject TEXT, to_name TEXT, to_email TEXT,
  sent TEXT, preview TEXT, nudged INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS ibm_items(
  id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT, title TEXT, status TEXT, due TEXT,
  section TEXT, detail TEXT, origin TEXT, updated TEXT);
CREATE TABLE IF NOT EXISTS ibm_files(
  path TEXT PRIMARY KEY, mtime REAL, source TEXT, items INTEGER, note TEXT, updated TEXT);
CREATE TABLE IF NOT EXISTS drafts(
  id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, ref_id TEXT, to_name TEXT, to_email TEXT,
  subject TEXT, body TEXT, status TEXT, created TEXT);
CREATE TABLE IF NOT EXISTS briefs(day TEXT PRIMARY KEY, text TEXT, created TEXT);
CREATE TABLE IF NOT EXISTS log(id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, kind TEXT, text TEXT);
"""


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def conn():
    c = sqlite3.connect(DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


def init():
    with _lock, conn() as c:
        c.executescript(SCHEMA)


def q(sql, args=()):
    with _lock, conn() as c:
        return [dict(r) for r in c.execute(sql, args).fetchall()]


def x(sql, args=()):
    with _lock, conn() as c:
        cur = c.execute(sql, args)
        return cur.lastrowid


def many(sql, rows):
    with _lock, conn() as c:
        c.executemany(sql, rows)


def log(kind, text):
    x("INSERT INTO log(ts, kind, text) VALUES(?,?,?)", (now_iso(), kind, text))
