"""Store単体: 履歴順序の安定性と、スキーマの版管理(マイグレーション)。"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from sentinel_core.memory import store as store_mod
from sentinel_core.memory.store import MIGRATIONS, SCHEMA_VERSION, SchemaTooNewError, Store


def test_history_preserves_insertion_order(tmp_path: Path):
    store = Store(tmp_path / "t.db")
    sid = store.ensure_session(None, None)
    # created_at は秒精度なので、同一秒に大量に入れても順序が保たれるかを検証
    for i in range(30):
        store.add_message(sid, "user" if i % 2 == 0 else "assistant", f"m{i}")

    hist = store.history(sid, limit=30)
    assert [h["content"] for h in hist] == [f"m{i}" for i in range(30)]


def test_history_limit_returns_most_recent(tmp_path: Path):
    store = Store(tmp_path / "t.db")
    sid = store.ensure_session(None, None)
    for i in range(10):
        store.add_message(sid, "user", f"m{i}")

    hist = store.history(sid, limit=3)
    assert [h["content"] for h in hist] == ["m7", "m8", "m9"]


def test_ensure_session_reuses_existing(tmp_path: Path):
    store = Store(tmp_path / "t.db")
    sid = store.ensure_session(None, "sera")
    assert store.ensure_session(sid, None) == sid
    assert len(store.list_sessions()) == 1


# --- 版管理とマイグレーション(B8) ---

V0_SCHEMA = """
CREATE TABLE sessions (id TEXT PRIMARY KEY, title TEXT, character_id TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, archived INTEGER DEFAULT 0);
CREATE TABLE messages (id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id),
  role TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL);
INSERT INTO sessions VALUES ('s1', NULL, NULL, '2026-07-08T00:00:00Z', '2026-07-08T00:00:00Z', 0);
INSERT INTO messages VALUES ('m1', 's1', 'user', '古い会話', '2026-07-08T00:00:00Z');
"""


def test_new_db_is_at_latest_version_without_backup(tmp_path: Path):
    db = tmp_path / "t.db"
    store = Store(db)
    assert store.schema_version == SCHEMA_VERSION
    assert not list(tmp_path.glob("*.bak-*"))


def test_legacy_db_is_migrated_and_backed_up(tmp_path: Path):
    """版管理導入前(user_version=0)のDBも、会話を残したまま最新版へ上がる。"""
    db = tmp_path / "t.db"
    with closing(sqlite3.connect(db)) as c:
        c.executescript(V0_SCHEMA)

    store = Store(db)

    assert store.schema_version == SCHEMA_VERSION
    assert store.history("s1") == [{"role": "user", "content": "古い会話"}]
    backup = tmp_path / "t.db.bak-v0"
    assert backup.exists()
    with closing(sqlite3.connect(backup)) as c:
        assert c.execute("SELECT content FROM messages").fetchone()[0] == "古い会話"


def test_reopening_latest_db_does_not_backup_again(tmp_path: Path):
    db = tmp_path / "t.db"
    Store(db)
    Store(db)
    assert not list(tmp_path.glob("*.bak-*"))


def test_newer_db_is_refused(tmp_path: Path):
    db = tmp_path / "t.db"
    Store(db)
    with closing(sqlite3.connect(db)) as c:
        c.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    with pytest.raises(SchemaTooNewError):
        Store(db)


def test_failed_migration_keeps_previous_version(tmp_path: Path, monkeypatch):
    db = tmp_path / "t.db"
    Store(db)
    broken = [*MIGRATIONS, "CREATE TABLE ok_part (x INTEGER); THIS IS NOT SQL"]
    monkeypatch.setattr(store_mod, "MIGRATIONS", broken)
    monkeypatch.setattr(store_mod, "SCHEMA_VERSION", len(broken))

    with pytest.raises(sqlite3.OperationalError):
        Store(db)

    with closing(sqlite3.connect(db)) as c:
        assert c.execute("PRAGMA user_version").fetchone()[0] == len(MIGRATIONS)
        tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master")}
    assert "ok_part" not in tables  # 失敗した版の途中の変更も残らない


def test_state_roundtrip(tmp_path: Path):
    store = Store(tmp_path / "t.db")
    assert store.get_state("k") is None
    store.set_state("k", "a")
    store.set_state("k", "b")
    assert store.get_state("k") == "b"
