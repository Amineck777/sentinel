"""会話永続化(仕様 §6 のサブセット: sessions/messages)。

Phase 1では最小限。tool_calls/approvals/RAG系テーブルはPhase 2/3で
migrations機構ごと導入する(いまはuser_version=1として単純適用)。
"""

from __future__ import annotations

import sqlite3
import time
import uuid
from contextlib import closing
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY,
  title TEXT,
  character_id TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  archived INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL REFERENCES sessions(id),
  role TEXT NOT NULL CHECK(role IN ('user','assistant','tool','system')),
  content TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, created_at);
"""


def _now() -> str:
    # UTC・ISO 8601。表示時のローカライズはUI側の責務
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _new_id() -> str:
    return uuid.uuid4().hex


class Store:
    def __init__(self, db_path: Path) -> None:
        self._path = db_path
        with closing(self._connect()) as c, c:
            c.execute("PRAGMA journal_mode=WAL")  # 読み書き並行時の安定性
            c.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        c = sqlite3.connect(self._path)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        return c

    # --- sessions ---
    def ensure_session(self, session_id: str | None, character_id: str | None) -> str:
        # closing=接続を確実に閉じる / 内側の `c`=トランザクション(commit/rollback)
        with closing(self._connect()) as c, c:
            if session_id:
                row = c.execute("SELECT id FROM sessions WHERE id=?", (session_id,)).fetchone()
                if row:
                    return session_id
            sid = session_id or _new_id()
            now = _now()
            c.execute(
                "INSERT INTO sessions(id,title,character_id,created_at,updated_at) "
                "VALUES(?,?,?,?,?)",
                (sid, None, character_id, now, now),
            )
            return sid

    def list_sessions(self, limit: int = 50) -> list[dict[str, Any]]:
        with closing(self._connect()) as c:
            rows = c.execute(
                "SELECT * FROM sessions WHERE archived=0 "
                "ORDER BY updated_at DESC, rowid DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    # --- messages ---
    def add_message(self, session_id: str, role: str, content: str) -> str:
        mid = _new_id()
        with closing(self._connect()) as c, c:
            c.execute(
                "INSERT INTO messages(id,session_id,role,content,created_at) VALUES(?,?,?,?,?)",
                (mid, session_id, role, content, _now()),
            )
            c.execute("UPDATE sessions SET updated_at=? WHERE id=?", (_now(), session_id))
        return mid

    def history(self, session_id: str, limit: int = 40) -> list[dict[str, str]]:
        """LLMへ渡す直近履歴(OpenAI形式)。

        created_at は秒精度で同値になり得るため、挿入順が確定する rowid で並べる。
        """
        with closing(self._connect()) as c:
            rows = c.execute(
                "SELECT role, content FROM messages "
                "WHERE session_id=? AND role IN ('user','assistant') "
                "ORDER BY rowid DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]
