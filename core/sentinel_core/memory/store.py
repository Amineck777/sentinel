"""会話永続化(仕様 §6 のサブセット: sessions/messages/kv)。

スキーマは MIGRATIONS で版管理する(PRAGMA user_version = 適用済みの版)。
- 版を上げるときは MIGRATIONS の末尾に追加するだけ。既存の項目は書き換えない
- 既存DBに未適用の版があれば、適用前に `sentinel.db.bak-v{旧版}` へ複製する
  (会話は10年残す一次記録なので、移行の失敗で失わない)
- 自分より新しい版のDB(新しいアプリで開いたもの)は開かずに止める
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sentinel_core.memory.budget import estimate_message_tokens

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

# 版4: 記憶 v1 の土台(ADR 0116)。
# - 発言ごとに、どのキャラとの会話かを残す(出来事をキャラ別に思い出すため)。
#   既存の発言は、そのセッションのキャラで埋める
# - セッションを「キャラごとの最新」で引くための索引(再起動後に会話を続けるため)
# - turn_logs: 返答1回ごとの自己観測ログ(E.V.A. 仕様 v0.2 §4.1)。
#   どのモデル・人格の版で、何を思い出し、何秒かかったかを残し、後から評価に使う
_V4 = """
ALTER TABLE messages ADD COLUMN character_id TEXT;
UPDATE messages SET character_id =
  (SELECT s.character_id FROM sessions s WHERE s.id = messages.session_id);
CREATE INDEX IF NOT EXISTS idx_sessions_character ON sessions(character_id, updated_at);
CREATE TABLE IF NOT EXISTS turn_logs (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  message_id TEXT,
  character_id TEXT,
  model TEXT,
  persona_hash TEXT,
  prompt_version TEXT,
  recalled_ids TEXT NOT NULL DEFAULT '[]',
  started_at TEXT NOT NULL,
  first_token_ms INTEGER,
  total_ms INTEGER,
  prompt_tokens_est INTEGER,
  prompt_tokens INTEGER,
  completion_tokens INTEGER,
  error TEXT
);
CREATE INDEX IF NOT EXISTS idx_turn_logs_session ON turn_logs(session_id, started_at)
"""

# 版5: 長期記憶(ADR 0116 の PR2)。どれも messages(原文)から作る二次記録で、作り直せる
# - episodes: 出来事。会話のまとまり1つにつき1件。キャラ別に思い出す(論点5)
#   pad_* は将来の疑似感情用に空で用意しておく(ロードマップ §5 のエピソード初版スキーマ)
# - facts: マスターについての事実。全キャラで共有する。訂正は上書きせず、
#   古い方を superseded にして superseded_by で新しい方を指す(論点6)
# - memory_fts: キーワード検索の索引(FTS5 の trigram。日本語を3文字ずつ区切って引く)
# - memory_jobs: 記憶づくりの記録。どの発言(rowid の範囲)まで記憶にしたかの目印も兼ねる
_V5 = """
CREATE TABLE IF NOT EXISTS episodes (
  id TEXT PRIMARY KEY,
  character_id TEXT,
  session_id TEXT NOT NULL,
  started_at TEXT NOT NULL,
  ended_at TEXT NOT NULL,
  summary TEXT NOT NULL,
  importance REAL NOT NULL DEFAULT 0.5,
  source_message_ids TEXT NOT NULL DEFAULT '[]',
  status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','forgotten')),
  pad_valence REAL,
  pad_arousal REAL,
  pad_dominance REAL,
  extractor_model TEXT,
  schema_version INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_episodes_character ON episodes(character_id, ended_at);
CREATE TABLE IF NOT EXISTS facts (
  id TEXT PRIMARY KEY,
  category TEXT NOT NULL,
  content TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'fact' CHECK(kind IN ('fact','inference')),
  confidence REAL NOT NULL DEFAULT 0.5,
  importance REAL NOT NULL DEFAULT 0.5,
  pinned INTEGER NOT NULL DEFAULT 0,
  expires_at TEXT,
  source_message_ids TEXT NOT NULL DEFAULT '[]',
  source_character_id TEXT,
  status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','superseded','forgotten')),
  superseded_by TEXT,
  extractor_model TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_facts_status ON facts(status, importance);
CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
  text, item_type UNINDEXED, item_id UNINDEXED, tokenize='trigram'
);
CREATE TABLE IF NOT EXISTS memory_jobs (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  character_id TEXT,
  from_rowid INTEGER NOT NULL,
  to_rowid INTEGER NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('done','skipped','failed')),
  model TEXT,
  n_episodes INTEGER NOT NULL DEFAULT 0,
  n_facts INTEGER NOT NULL DEFAULT 0,
  n_corrections INTEGER NOT NULL DEFAULT 0,
  started_at TEXT NOT NULL,
  duration_ms INTEGER,
  error TEXT
);
CREATE INDEX IF NOT EXISTS idx_memory_jobs_session ON memory_jobs(session_id, to_rowid)
"""

MIGRATIONS: list[str] = [_V1, _V2, _V3, _V4, _V5]
SCHEMA_VERSION = len(MIGRATIONS)


class SchemaTooNewError(RuntimeError):
    """DBの版がこのアプリより新しい(古いアプリで開くと壊す恐れがある)。"""


def _statements(script: str) -> list[str]:
    # 移行SQLは単純なDDLだけを書く(トリガー等の ; を含む文は使わない)前提で分割する
    return [stmt.strip() for stmt in script.split(";") if stmt.strip()]


def now_iso() -> str:
    """今の時刻(UTC・ISO 8601・秒精度)。DB に入れる時刻はすべてこの形。"""
    return _now()


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

    @property
    def path(self) -> Path:
        """DB ファイルの場所(長期記憶 memory/longterm.py が同じファイルを開くため)。"""
        return self._path

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

    def session_owner(self, session_id: str) -> tuple[bool, str | None]:
        """(セッションがあるか, そのセッションのキャラID)。汎用モードのキャラIDは None。"""
        with closing(self._connect()) as c:
            row = c.execute(
                "SELECT character_id FROM sessions WHERE id=?", (session_id,)
            ).fetchone()
        return (False, None) if row is None else (True, row["character_id"])

    def resumable_session(self, character_id: str | None, within_hours: float) -> str | None:
        """そのキャラの最新セッションが within_hours 時間以内に話したものなら、その ID。

        アプリを再起動しても、少し前の会話の続きとして扱うため(ADR 0116 の短期記憶)。
        汎用モード(character_id=None)も「汎用モード同士」で続ける。
        """
        if within_hours <= 0:
            return None  # 0 以下なら続けない(毎回新しいセッション)
        with closing(self._connect()) as c:
            # `IS ?` は NULL 同士も一致とみなす(`= ?` だと汎用モードが一致しない)
            row = c.execute(
                "SELECT id, updated_at FROM sessions WHERE archived=0 AND character_id IS ? "
                "ORDER BY updated_at DESC, rowid DESC LIMIT 1",
                (character_id,),
            ).fetchone()
        if row is None:
            return None
        updated = datetime.strptime(row["updated_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        if datetime.now(UTC) - updated > timedelta(hours=within_hours):
            return None
        return str(row["id"])

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
        self,
        session_id: str,
        role: str,
        content: str,
        model: str | None = None,
        character_id: str | None = None,
    ) -> str:
        """発言を1件追記する。character_id は「どのキャラとの会話か」(汎用モードは None)。"""
        mid = _new_id()
        with closing(self._connect()) as c, c:
            c.execute(
                "INSERT INTO messages(id,session_id,role,content,created_at,model,character_id) "
                "VALUES(?,?,?,?,?,?,?)",
                (mid, session_id, role, content, _now(), model, character_id),
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

    def recent_history(
        self, session_id: str, max_tokens: int, max_messages: int = 200
    ) -> list[dict[str, str]]:
        """短期記憶: 新しい発言から順に、合計が max_tokens に収まるところまで(OpenAI形式)。

        発言数ではなくトークン数で切るのは、長い発言が続いても文脈(num_ctx)から
        あふれないようにするため。最新の1発言だけは、長すぎても必ず入れる
        (入れないと、今話しかけられた内容が LLM に届かない)。
        max_messages は、DB から読む件数の上限(極端に短い発言が大量にある場合の歯止め)。
        """
        with closing(self._connect()) as c:
            rows = c.execute(
                "SELECT role, content FROM messages "
                "WHERE session_id=? AND role IN ('user','assistant') "
                "ORDER BY rowid DESC LIMIT ?",
                (session_id, max_messages),
            ).fetchall()
        picked: list[dict[str, str]] = []
        used = 0
        for r in rows:  # 新しい順に見ていく
            cost = estimate_message_tokens(r["content"])
            if picked and used + cost > max_tokens:
                break
            picked.append({"role": r["role"], "content": r["content"]})
            used += cost
        return list(reversed(picked))  # LLM には古い順で渡す

    # --- turn_logs(自己観測ログ) ---
    def add_turn_log(
        self,
        *,
        session_id: str,
        message_id: str | None,
        character_id: str | None,
        model: str | None,
        persona_hash: str | None,
        prompt_version: str,
        recalled_ids: list[str],
        started_at: str,
        first_token_ms: int | None,
        total_ms: int,
        prompt_tokens_est: int,
        prompt_tokens: int | None,
        completion_tokens: int | None,
        error: str | None,
    ) -> str:
        """返答1回分の観測を記録する(項目の意味は版4の turn_logs を参照)。"""
        lid = _new_id()
        with closing(self._connect()) as c, c:
            c.execute(
                "INSERT INTO turn_logs(id,session_id,message_id,character_id,model,persona_hash,"
                "prompt_version,recalled_ids,started_at,first_token_ms,total_ms,"
                "prompt_tokens_est,prompt_tokens,completion_tokens,error) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    lid,
                    session_id,
                    message_id,
                    character_id,
                    model,
                    persona_hash,
                    prompt_version,
                    json.dumps(recalled_ids),
                    started_at,
                    first_token_ms,
                    total_ms,
                    prompt_tokens_est,
                    prompt_tokens,
                    completion_tokens,
                    error,
                ),
            )
        return lid

    def turn_logs(self, session_id: str) -> list[dict[str, Any]]:
        """セッションの観測ログ(古い順)。評価や確認用。"""
        with closing(self._connect()) as c:
            rows = c.execute(
                "SELECT * FROM turn_logs WHERE session_id=? ORDER BY rowid", (session_id,)
            ).fetchall()
        return [dict(r) for r in rows]

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
