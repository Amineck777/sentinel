"""Store単体: 履歴順序の安定性(同一秒内の挿入でも順序が崩れないこと)。"""
from __future__ import annotations

from pathlib import Path

from sentinel_core.memory.store import Store


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
