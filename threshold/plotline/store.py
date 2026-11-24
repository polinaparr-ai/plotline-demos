"""Conversation history and findings. SQLite here; Supabase Postgres in production.

Conversations are scoped to (user, dashboard). Findings are scoped to a dashboard and start
as drafts; once approved they are fed back to the assistant as context for later questions.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import sqlite3
import threading
import uuid

from plotline.paths import STATE_DB as DB

DB.parent.mkdir(exist_ok=True)
_lock = threading.Lock()


def _con() -> sqlite3.Connection:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.executescript("""
        CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY, user TEXT, dashboard_id TEXT, created_at TEXT, messages TEXT);
        CREATE TABLE IF NOT EXISTS findings (
            id TEXT PRIMARY KEY, dashboard_id TEXT, dashboard_version INT, title TEXT, summary TEXT,
            question TEXT, evidence TEXT, figure TEXT, saved_by TEXT, created_at TEXT,
            status TEXT, approved_by TEXT);
        CREATE TABLE IF NOT EXISTS preferences (
            user TEXT PRIMARY KEY, preset TEXT, custom TEXT, updated_at TEXT);
    """)
    return con


def now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def load_conversation(conv_id: str, user: str, dashboard_id: str) -> list:
    with _lock, _con() as con:
        r = con.execute("SELECT messages FROM conversations WHERE id=? AND user=? AND dashboard_id=?",
                        (conv_id, user, dashboard_id)).fetchone()
        return json.loads(r["messages"]) if r else []


def save_conversation(conv_id: str, user: str, dashboard_id: str, messages: list) -> None:
    with _lock, _con() as con:
        con.execute("""INSERT INTO conversations (id, user, dashboard_id, created_at, messages) VALUES (?,?,?,?,?)
                       ON CONFLICT(id) DO UPDATE SET messages=excluded.messages""",
                    (conv_id, user, dashboard_id, now(), json.dumps(messages, default=str)))


def save_finding(*, dashboard_id, dashboard_version, title, summary, question, evidence, figure, saved_by) -> dict:
    f = {"id": uuid.uuid4().hex[:10], "dashboard_id": dashboard_id, "dashboard_version": dashboard_version,
         "title": title, "summary": summary, "question": question, "evidence": evidence or [],
         "figure": figure, "saved_by": saved_by, "created_at": now(), "status": "draft", "approved_by": None}
    with _lock, _con() as con:
        con.execute("INSERT INTO findings VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (f["id"], dashboard_id, dashboard_version, title, summary, question, json.dumps(f["evidence"]),
                     json.dumps(figure) if figure else None, saved_by, f["created_at"], "draft", None))
    return f


def list_findings(dashboard_id: str, status: str | None = None) -> list:
    with _lock, _con() as con:
        q = "SELECT * FROM findings WHERE dashboard_id=?" + (" AND status=?" if status else "") + " ORDER BY created_at DESC"
        rows = con.execute(q, (dashboard_id, status) if status else (dashboard_id,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["evidence"] = json.loads(d["evidence"] or "[]")
        d["figure"] = json.loads(d["figure"]) if d["figure"] else None
        out.append(d)
    return out


def approve_finding(fid: str, approved_by: str) -> None:
    with _lock, _con() as con:
        con.execute("UPDATE findings SET status='approved', approved_by=? WHERE id=?", (approved_by, fid))


def get_preferences(user: str) -> dict | None:
    with _lock, _con() as con:
        r = con.execute("SELECT preset, custom, updated_at FROM preferences WHERE user=?", (user,)).fetchone()
        return dict(r) if r else None


def set_preferences(user: str, preset: str, custom: str) -> None:
    with _lock, _con() as con:
        con.execute("""INSERT INTO preferences (user, preset, custom, updated_at) VALUES (?,?,?,?)
                       ON CONFLICT(user) DO UPDATE SET preset=excluded.preset, custom=excluded.custom,
                       updated_at=excluded.updated_at""", (user, preset, custom, now()))
