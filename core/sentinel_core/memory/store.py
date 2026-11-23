"""会話永続化(仕様 §6 のサブセット: sessions/messages/kv)。

スキーマは MIGRATIONS で版管理する(PRAGMA user_version = 適用済みの版)。
- 版を上げるときは MIGRATIONS の末尾に追加するだけ。既存の項目は書き換えない
- 既存DBに未適用の版があれば、適用前に `sentinel.db.bak-v{旧版}` へ複製する
  (会話は10年残す一次記録なので、移行の失敗で失わない)
- 自分より新しい版のDB(新しいアプリで開いたもの)は開かずに止める
"""

from __future__ import annotations

import sqlite3
import time
import uuid
from contextlib import closing
from pathlib import Path
from typing import Any

# 版1: Phase 1 のスキーマ。導入前のDB(user_version=0)にも IF NOT EXISTS で安全に適用できる
_V1 = """
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

# 版2: アプリの状態(最後に選んだキャラなど)。
# 設定ファイルはユーザーが書くもの、こちらはアプリが書くもの
_V2 = """
CREATE TABLE IF NOT EXISTS kv (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
"""

# 版3: 発言ごとに、どのモデルが生成したかを残す(assistant のみ。user は NULL)。
# 会話を後で学習データにするとき、モデルの版を混ぜないように選り分けるため
_V3 = """
ALTER TABLE messages ADD COLUMN model TEXT
"""

MIGRATIONS: list[str] = [_V1, _V2, _V3]
SCHEMA_VERSION = len(MIGRATIONS)


class SchemaTooNewError(RuntimeError):
    """DBの版がこのアプリより新しい(古いアプリで開くと壊す恐れがある)。"""


def _statements(script: str) -> list[str]:
    # 移行SQLは単純なDDLだけを書く(トリガー等の ; を含む文は使わない)前提で分割する
    return [stmt.strip() for stmt in script.split(";") if stmt.strip()]


def _now() -> str:
    # UTC・ISO 8601。表示時のローカライズはUI側の責務
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _new_id() -> str:
    return uuid.uuid4().hex


class Store:
    def __init__(self, db_path: Path) -> None:
        self._path = db_path
        # 移行はトランザクションを自分で区切るため autocommit(isolation_level=None)の接続で行う
        with closing(sqlite3.connect(self._path, isolation_level=None)) as c:
            c.execute("PRAGMA journal_mode=WAL")  # 読み書き並行時の安定性
            self._migrate(c)

    def _migrate(self, c: sqlite3.Connection) -> None:
        current = int(c.execute("PRAGMA user_version").fetchone()[0])
        if current > SCHEMA_VERSION:
            raise SchemaTooNewError(
                f"DBの版 {current} はこのアプリ(版 {SCHEMA_VERSION})より新しいため開けません: "
                f"{self._path}"
            )
        if current == SCHEMA_VERSION:
            return
        has_tables = c.execute("SELECT count(*) FROM sqlite_master").fetchone()[0] > 0
        if has_tables:  # 新規DBは退避不要。版0でも中身があれば(版管理導入前のDB)退避する
            self._backup(c, current)
        for version in range(current + 1, SCHEMA_VERSION + 1):
            # 版ごとに1トランザクション。途中で失敗しても、成功した版までは確定する
            c.execute("BEGIN")
            try:
                for stmt in _statements(MIGRATIONS[version - 1]):
                    c.execute(stmt)
                c.execute(f"PRAGMA user_version = {version}")
                c.execute("COMMIT")
            except BaseException:
                c.execute("ROLLBACK")
                raise

    def _backup(self, c: sqlite3.Connection, version: int) -> None:
        dest_path = self._path.with_name(f"{self._path.name}.bak-v{version}")
        if dest_path.exists():
            return  # 同じ版の退避が既にある(前回の移行が途中で失敗した等)。上書きしない
        with closing(sqlite3.connect(dest_path)) as dest:
            c.backup(dest)

    @property
    def schema_version(self) -> int:
        with closing(self._connect()) as c:
            return int(c.execute("PRAGMA user_version").fetchone()[0])

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
    def add_message(
        self, session_id: str, role: str, content: str, model: str | None = None
    ) -> str:
        mid = _new_id()
        with closing(self._connect()) as c, c:
            c.execute(
                "INSERT INTO messages(id,session_id,role,content,created_at,model) "
                "VALUES(?,?,?,?,?,?)",
                (mid, session_id, role, content, _now(), model),
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

    # --- kv(アプリの状態) ---
    def get_state(self, key: str) -> str | None:
        with closing(self._connect()) as c:
            row = c.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return None if row is None else str(row["value"])

    def set_state(self, key: str, value: str) -> None:
        with closing(self._connect()) as c, c:
            c.execute(
                "INSERT INTO kv(key,value,updated_at) VALUES(?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET "
                "value=excluded.value, updated_at=excluded.updated_at",
                (key, value, _now()),
            )
