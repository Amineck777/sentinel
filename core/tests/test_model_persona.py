"""モデル側に人格を持つキャラ(例: Ollama の eva)をチャットにつなぐ経路の検査。

- character.yaml の llm.model / llm.system_prompt: model を読む
- system を送らない(送ると Modelfile の SYSTEM が上書きされる)
- このターンのモデル名を LLM に渡し、発言と一緒に SQLite に残す
- 思考オフ(reasoning_effort="none")を送り、受け付けないサーバーでは外してやり直す
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from collections.abc import AsyncIterator
from contextlib import closing
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from sentinel_core.api.app import create_app
from sentinel_core.character.pack import load_pack
from sentinel_core.llm.openai_compat import OpenAICompatClient
from sentinel_core.settings import Settings

TOKEN = "test-token"
H = {"X-Sentinel-Token": TOKEN}


class RecordingLLM:
    """受け取った messages と model を覚えておくモック。"""

    def __init__(self) -> None:
        self.calls: list[tuple[list[dict[str, str]], str | None]] = []

    async def stream_chat(self, messages, *, model=None) -> AsyncIterator[str]:
        self.calls.append((messages, model))
        yield "かしこまりました、マスター。"

    async def is_reachable(self) -> bool:
        return True


def _write_pack(root: Path, manifest: str) -> None:
    root.mkdir(parents=True)
    (root / "character.yaml").write_text(manifest, encoding="utf-8")


EVA_YAML = (
    "schema_version: 1\nid: eva\ndisplay_name: エヴァ\nllm:\n  model: eva\n  system_prompt: model\n"
)


def _turn(c: TestClient, content: str) -> str:
    with c.websocket_connect(f"/v1/stream?token={TOKEN}") as ws:
        sid = c.post("/v1/chat", headers=H, json={"content": content}).json()["session_id"]
        while ws.receive_json()["type"] != "message_done":
            pass
    return str(sid)


def test_model_persona_pack_is_loaded(tmp_path: Path):
    _write_pack(tmp_path / "eva", EVA_YAML)
    pack = load_pack(tmp_path / "eva")
    assert pack.valid and pack.model == "eva" and pack.use_model_system


@pytest.mark.parametrize(
    "llm_block",
    ["llm:\n  system_prompt: model\n", "llm:\n  model: eva\n  system_prompt: modelfile\n"],
)
def test_invalid_llm_block_disables_pack(tmp_path: Path, llm_block: str):
    _write_pack(tmp_path / "eva", "schema_version: 1\nid: eva\n" + llm_block)
    pack = load_pack(tmp_path / "eva")
    assert not pack.valid and pack.error


def test_chat_uses_model_persona_and_records_model(tmp_path: Path):
    settings = Settings.load(data_dir=tmp_path)
    _write_pack(settings.characters_dir / "eva", EVA_YAML)
    llm = RecordingLLM()
    app = create_app(settings=settings, token=TOKEN, dev=True, llm=llm)
    with TestClient(app) as c:
        assert c.post("/v1/characters/eva/activate", headers=H).json()["ok"]
        assert c.get("/v1/system/health", headers=H).json()["chat_model"] == "eva"
        sid = _turn(c, "ただいま")

    messages, model = llm.calls[0]
    assert model == "eva"
    assert all(m["role"] != "system" for m in messages)  # Modelfile の SYSTEM を活かす
    assert messages[-1] == {"role": "user", "content": "ただいま"}

    with closing(sqlite3.connect(settings.db_path)) as db:
        rows = db.execute(
            "SELECT role, model FROM messages WHERE session_id=? ORDER BY rowid", (sid,)
        ).fetchall()
    assert rows == [("user", None), ("assistant", "eva")]


def test_generic_mode_keeps_system_prompt_and_default_model(tmp_path: Path):
    settings = Settings.load(data_dir=tmp_path)
    llm = RecordingLLM()
    app = create_app(settings=settings, token=TOKEN, dev=True, llm=llm)
    with TestClient(app) as c:
        assert c.get("/v1/system/health", headers=H).json()["chat_model"] == settings.chat_model
        _turn(c, "やあ")
    messages, model = llm.calls[0]
    assert model is None and messages[0]["role"] == "system"


# --- OpenAI互換クライアント(実サーバーの代わりに httpx.MockTransport を使う)---


def _sse(*chunks: dict[str, Any]) -> str:
    lines = [f"data: {json.dumps({'choices': [{'delta': d}]})}" for d in chunks]
    return "\n\n".join([*lines, "data: [DONE]"]) + "\n\n"


async def _collect(client: OpenAICompatClient, **kw: Any) -> str:
    out = [d async for d in client.stream_chat([{"role": "user", "content": "hi"}], **kw)]
    await client.aclose()
    return "".join(out)


def test_think_off_is_sent_and_reasoning_is_ignored():
    seen: list[dict[str, Any]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(json.loads(req.content))
        body = _sse({"reasoning": "考え中…"}, {"content": "承知"}, {"content": "しました"})
        return httpx.Response(200, text=body)

    client = OpenAICompatClient("http://llm/v1", "base-model", think=False)
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    assert asyncio.run(_collect(client, model="eva")) == "承知しました"
    assert seen[0]["model"] == "eva" and seen[0]["reasoning_effort"] == "none"


def test_server_without_think_option_falls_back_once():
    seen: list[dict[str, Any]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        payload = json.loads(req.content)
        seen.append(payload)
        if "reasoning_effort" in payload:
            return httpx.Response(400, text="unknown field")
        return httpx.Response(200, text=_sse({"content": "ok"}))

    client = OpenAICompatClient("http://llm/v1", "base-model", think=False)
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    assert asyncio.run(_collect(client)) == "ok"
    assert [("reasoning_effort" in p) for p in seen] == [True, False]
    assert seen[1]["model"] == "base-model"


def test_think_on_sends_nothing_extra():
    seen: list[dict[str, Any]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(json.loads(req.content))
        return httpx.Response(200, text=_sse({"content": "ok"}))

    client = OpenAICompatClient("http://llm/v1", "m", think=True)
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    assert asyncio.run(_collect(client)) == "ok"
    assert "reasoning_effort" not in seen[0]
