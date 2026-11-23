"""会話ターンの保存方針と、キャラ選択の保持(Day 1 から記憶を汚さないための検査)。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi.testclient import TestClient

from sentinel_core.api.app import create_app
from sentinel_core.llm.client import LLMUnavailableError
from sentinel_core.settings import Settings

TOKEN = "test-token"
H = {"X-Sentinel-Token": TOKEN}


class OfflineLLM:
    async def stream_chat(self, messages, *, model=None) -> AsyncIterator[str]:
        await asyncio.sleep(0)
        raise LLMUnavailableError("(オフライン応答)テスト")
        yield ""  # pragma: no cover  (async generator にするため)

    async def is_reachable(self) -> bool:
        return False


class CutOffLLM:
    """途中まで生成してから切断される。"""

    async def stream_chat(self, messages, *, model=None) -> AsyncIterator[str]:
        yield "途中まで"
        raise LLMUnavailableError("(オフライン応答)切断")

    async def is_reachable(self) -> bool:
        return False


class EchoLLM:
    async def stream_chat(self, messages, *, model=None) -> AsyncIterator[str]:
        yield "ok"

    async def is_reachable(self) -> bool:
        return True


def _run_turn(c: TestClient, content: str) -> tuple[str, list[dict]]:
    events: list[dict] = []
    with c.websocket_connect(f"/v1/stream?token={TOKEN}") as ws:
        sid = c.post("/v1/chat", headers=H, json={"content": content}).json()["session_id"]
        while True:
            ev = ws.receive_json()
            events.append(ev)
            if ev["type"] in ("message_done", "notice"):
                break
    return sid, events


def test_offline_reply_is_shown_but_not_saved(tmp_path: Path):
    app = create_app(Settings.load(data_dir=tmp_path), token=TOKEN, dev=True, llm=OfflineLLM())
    with TestClient(app) as c:
        sid, events = _run_turn(c, "やあ")
        assert events[-1] == {"type": "notice", "level": "warn", "text": "(オフライン応答)テスト"}
        history = app.state.store.history(sid)
    assert history == [{"role": "user", "content": "やあ"}]


def test_partial_reply_saves_only_generated_text(tmp_path: Path):
    app = create_app(Settings.load(data_dir=tmp_path), token=TOKEN, dev=True, llm=CutOffLLM())
    with TestClient(app) as c, c.websocket_connect(f"/v1/stream?token={TOKEN}") as ws:
        sid = c.post("/v1/chat", headers=H, json={"content": "やあ"}).json()["session_id"]
        types = []
        while "message_done" not in types:
            types.append(ws.receive_json()["type"])
        history = app.state.store.history(sid)
    assert types == ["token", "notice", "message_done"]
    assert history[-1] == {"role": "assistant", "content": "途中まで"}


def _make_pack(root: Path, char_id: str) -> None:
    pack = root / "characters" / char_id
    (pack / "persona").mkdir(parents=True)
    (pack / "character.yaml").write_text(
        f"schema_version: 1\nid: {char_id}\ndisplay_name: {char_id}\n", encoding="utf-8"
    )
    (pack / "persona" / "persona.md").write_text("テスト人格。", encoding="utf-8")


def _active(tmp_path: Path) -> str | None:
    app = create_app(Settings.load(data_dir=tmp_path), token=TOKEN, dev=True, llm=EchoLLM())
    with TestClient(app) as c:
        return c.get("/v1/system/health", headers=H).json()["active_character"]


def test_config_character_is_active_at_startup(tmp_path: Path):
    _make_pack(tmp_path, "sera")
    (tmp_path / "config.yaml").write_text("character:\n  active: sera\n", encoding="utf-8")
    assert _active(tmp_path) == "sera"


def test_selected_character_survives_restart(tmp_path: Path):
    _make_pack(tmp_path, "sera")
    _make_pack(tmp_path, "yuuka")
    (tmp_path / "config.yaml").write_text("character:\n  active: sera\n", encoding="utf-8")

    app = create_app(Settings.load(data_dir=tmp_path), token=TOKEN, dev=True, llm=EchoLLM())
    with TestClient(app) as c:
        c.get("/v1/characters", headers=H)
        assert c.post("/v1/characters/yuuka/activate", headers=H).json()["ok"]

    assert _active(tmp_path) == "yuuka"  # 設定より、最後に選んだものが優先


def test_generic_mode_choice_survives_restart(tmp_path: Path):
    _make_pack(tmp_path, "sera")
    (tmp_path / "config.yaml").write_text("character:\n  active: sera\n", encoding="utf-8")

    app = create_app(Settings.load(data_dir=tmp_path), token=TOKEN, dev=True, llm=EchoLLM())
    with TestClient(app) as c:
        c.post("/v1/characters/none/activate", headers=H)

    assert _active(tmp_path) is None


def test_missing_pack_falls_back_without_forgetting(tmp_path: Path):
    """Packを一時的に外しても、選択は消さない(戻せば次の起動で復帰する)。"""
    _make_pack(tmp_path, "sera")
    app = create_app(Settings.load(data_dir=tmp_path), token=TOKEN, dev=True, llm=EchoLLM())
    with TestClient(app) as c:
        c.get("/v1/characters", headers=H)
        c.post("/v1/characters/sera/activate", headers=H)

    pack = tmp_path / "characters" / "sera"
    moved = tmp_path / "sera.off"
    pack.rename(moved)
    assert _active(tmp_path) is None
    moved.rename(pack)
    assert _active(tmp_path) == "sera"
