"""スモークテスト: 認証・ヘルス・チャット一連・キャラ切替(モックLLM使用=仕様 §12.2)。"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import AsyncIterator

import pytest
from fastapi.testclient import TestClient

from sentinel_core.api.app import create_app
from sentinel_core.settings import Settings

TOKEN = "test-token"
H = {"X-Sentinel-Token": TOKEN}


class FakeLLM:
    """決定的なモック(実LLM不使用でエージェント側を検証する規約)。"""

    async def stream_chat(self, messages) -> AsyncIterator[str]:
        # システムプロンプトの内容を応答に混ぜて、キャラ合成の検証に使う
        sys_prompt = messages[0]["content"]
        tag = "CHAR" if "キャラクター人格" in sys_prompt else "BASE"
        for chunk in [f"[{tag}]", "こんにちは"]:
            yield chunk

    async def is_reachable(self) -> bool:
        return False


@pytest.fixture()
def client(tmp_path: Path):
    settings = Settings.load(data_dir=tmp_path)
    # アダプタ差し替えはファクトリのDI引数で行う(ポート&アダプタの結線点)
    app = create_app(settings=settings, token=TOKEN, dev=True, llm=FakeLLM())
    with TestClient(app) as c:
        yield c, tmp_path


def test_auth_required(client):
    c, _ = client
    assert c.get("/v1/system/health").status_code == 401
    assert c.get("/v1/system/health", headers=H).status_code == 200


def test_chat_streams_and_persists(client):
    c, _ = client
    with c.websocket_connect(f"/v1/stream?token={TOKEN}") as ws:
        r = c.post("/v1/chat", headers=H, json={"content": "やあ"})
        assert r.status_code == 200
        sid = r.json()["session_id"]

        got_tokens, done = [], False
        for _ in range(10):
            ev = ws.receive_json()
            if ev["type"] == "token":
                got_tokens.append(ev["delta"])
            if ev["type"] == "message_done":
                done = True
                break
        assert done and "".join(got_tokens) == "[BASE]こんにちは"

    sessions = c.get("/v1/sessions", headers=H).json()["sessions"]
    assert sessions and sessions[0]["id"] == sid


def test_character_pack_activation(client):
    c, tmp = client
    # 最小のPackを配置(§16.1「フォルダを置けばキャラが増える」)
    pack = tmp / "characters" / "sera"
    (pack / "persona").mkdir(parents=True)
    (pack / "character.yaml").write_text(
        "schema_version: 1\nid: sera\ndisplay_name: セラ\n", encoding="utf-8"
    )
    (pack / "persona" / "persona.md").write_text("落ち着いた大人の女性。", encoding="utf-8")

    chars = c.get("/v1/characters", headers=H).json()
    assert any(x["id"] == "sera" and x["valid"] for x in chars["characters"])

    assert c.post("/v1/characters/sera/activate", headers=H).json()["ok"]

    with c.websocket_connect(f"/v1/stream?token={TOKEN}") as ws:
        c.post("/v1/chat", headers=H, json={"content": "おはよう"})
        text = ""
        for _ in range(10):
            ev = ws.receive_json()
            if ev["type"] == "token":
                text += ev["delta"]
            if ev["type"] == "message_done":
                break
        assert text.startswith("[CHAR]")  # キャラのシステムプロンプトが合成された


def test_invalid_pack_does_not_break(client):
    c, tmp = client
    bad = tmp / "characters" / "broken"
    bad.mkdir(parents=True)
    (bad / "character.yaml").write_text(": : :", encoding="utf-8")  # 壊れたYAML
    chars = c.get("/v1/characters", headers=H).json()["characters"]
    entry = next(x for x in chars if x["id"] == "broken")
    assert entry["valid"] is False and entry["error"]  # 無効化されるが起動は生きている
