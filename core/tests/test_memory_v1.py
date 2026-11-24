"""記憶 v1 の土台(ADR 0116 の PR1)の検査。

- 短期記憶: 発言数ではなくトークン数で切る / 再起動しても数時間以内なら会話を続ける
- 別キャラのセッションは続けない(出来事をキャラ別に覚えるため)
- 人格の文を1ファイルに置く file モード(コアが system として送る)
- 自己観測ログ(turn_logs): モデル・人格の版・時間・エラーを返答ごとに残す
- DB 版4: 既存の発言にキャラIDを埋める
- Modelfile の SYSTEM を人格ファイルから作るスクリプト
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sqlite3
from collections.abc import AsyncIterator
from contextlib import closing
from pathlib import Path
from typing import Any

import httpx
from fastapi.testclient import TestClient

from sentinel_core.api.app import create_app
from sentinel_core.character.pack import load_pack
from sentinel_core.llm.client import LLMUnavailableError
from sentinel_core.llm.openai_compat import OpenAICompatClient
from sentinel_core.memory import store as store_mod
from sentinel_core.memory.budget import estimate_message_tokens, estimate_tokens
from sentinel_core.memory.store import Store
from sentinel_core.settings import Settings

TOKEN = "test-token"
H = {"X-Sentinel-Token": TOKEN}
REPO = Path(__file__).resolve().parents[2]


class RecordingLLM:
    """受け取った messages を覚え、決まった返事を返すモック。"""

    def __init__(self, reply: str = "かしこまりました。") -> None:
        self.reply = reply
        self.calls: list[list[dict[str, str]]] = []
        self.last_usage: dict[str, int] | None = None

    async def stream_chat(self, messages, *, model=None) -> AsyncIterator[str]:
        self.calls.append(messages)
        self.last_usage = {"prompt_tokens": 42, "completion_tokens": 7}
        yield self.reply

    async def is_reachable(self) -> bool:
        return True


class OfflineLLM:
    async def stream_chat(self, messages, *, model=None) -> AsyncIterator[str]:
        await asyncio.sleep(0)
        raise LLMUnavailableError("(オフライン応答)テスト")
        yield ""  # pragma: no cover  (async generator にするため)

    async def is_reachable(self) -> bool:
        return False


def _pack(settings: Settings, char_id: str, llm_block: str = "") -> Path:
    root = settings.characters_dir / char_id
    (root / "persona").mkdir(parents=True)
    (root / "character.yaml").write_text(
        f"schema_version: 1\nid: {char_id}\ndisplay_name: {char_id}\n{llm_block}",
        encoding="utf-8",
    )
    return root


def _turn(c: TestClient, content: str, session_id: str | None = None) -> str:
    with c.websocket_connect(f"/v1/stream?token={TOKEN}") as ws:
        body: dict[str, Any] = {"content": content, "session_id": session_id}
        sid = c.post("/v1/chat", headers=H, json=body).json()["session_id"]
        while ws.receive_json()["type"] not in ("message_done", "notice"):
            pass
    return str(sid)


def _app(settings: Settings, llm: Any) -> Any:
    return create_app(settings=settings, token=TOKEN, dev=True, llm=llm)


# --- トークンの見積もり ---


def test_estimate_counts_japanese_per_char_and_ascii_per_four():
    assert estimate_tokens("こんにちは") == 5
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("abcde") == 2  # 端数は切り上げ(多めに見積もる)
    assert estimate_message_tokens("") == 4  # 区切りの分


# --- 短期記憶: トークン数で切る ---


def test_recent_history_is_cut_by_tokens_and_keeps_order(tmp_path: Path):
    store = Store(tmp_path / "t.db")
    sid = store.ensure_session(None, None)
    for i in range(10):
        store.add_message(sid, "user", f"発言{i}")  # 1件 = 3文字 + 4 = 7トークン
    hist = store.recent_history(sid, max_tokens=21)
    assert [h["content"] for h in hist] == ["発言7", "発言8", "発言9"]


def test_recent_history_always_keeps_latest_message(tmp_path: Path):
    store = Store(tmp_path / "t.db")
    sid = store.ensure_session(None, None)
    store.add_message(sid, "user", "短い")
    store.add_message(sid, "user", "長" * 100)
    hist = store.recent_history(sid, max_tokens=10)
    assert hist == [{"role": "user", "content": "長" * 100}]


# --- 再起動しても会話を続ける ---


def test_restart_continues_recent_session(tmp_path: Path):
    settings = Settings.load(data_dir=tmp_path)
    llm = RecordingLLM()
    with TestClient(_app(settings, llm)) as c:
        sid1 = _turn(c, "今日はカレーを作った")
    # 画面は再起動で session_id を忘れる(None で送る)が、コアが同じ会話を続ける
    with TestClient(_app(Settings.load(data_dir=tmp_path), llm)) as c:
        sid2 = _turn(c, "さっき何を作ったっけ")
    assert sid1 == sid2
    contents = [m["content"] for m in llm.calls[-1]]
    assert "今日はカレーを作った" in contents  # 再起動前の発言が短期記憶に入っている


def test_old_session_is_not_resumed(tmp_path: Path):
    settings = Settings.load(data_dir=tmp_path)
    with TestClient(_app(settings, RecordingLLM())) as c:
        sid1 = _turn(c, "やあ")
    # 最後に話したのが7時間前、ということにする(既定は6時間以内なら続ける)
    with closing(sqlite3.connect(settings.db_path)) as db, db:
        db.execute("UPDATE sessions SET updated_at='2000-01-01T00:00:00Z' WHERE id=?", (sid1,))
    with TestClient(_app(Settings.load(data_dir=tmp_path), RecordingLLM())) as c:
        assert _turn(c, "やあ") != sid1


def test_resume_can_be_turned_off(tmp_path: Path):
    (tmp_path / "config.yaml").write_text("memory:\n  session_resume_hours: 0\n", encoding="utf-8")
    with TestClient(_app(Settings.load(data_dir=tmp_path), RecordingLLM())) as c:
        sid1 = _turn(c, "やあ")
    with TestClient(_app(Settings.load(data_dir=tmp_path), RecordingLLM())) as c:
        assert _turn(c, "やあ") != sid1


def test_other_characters_session_is_not_continued(tmp_path: Path):
    settings = Settings.load(data_dir=tmp_path)
    _pack(settings, "eva")
    _pack(settings, "yuuka")
    llm = RecordingLLM()
    with TestClient(_app(settings, llm)) as c:
        assert c.post("/v1/characters/eva/activate", headers=H).json()["ok"]
        eva_sid = _turn(c, "エヴァへの話")
        assert c.post("/v1/characters/yuuka/activate", headers=H).json()["ok"]
        # 画面はエヴァのセッションIDを持ったまま送ってくるが、ユウカには引き継がない
        yuuka_sid = _turn(c, "ユウカへの話", session_id=eva_sid)
        assert yuuka_sid != eva_sid
        assert "エヴァへの話" not in [m["content"] for m in llm.calls[-1]]
        # エヴァに戻すと、エヴァとの会話の続きになる
        assert c.post("/v1/characters/eva/activate", headers=H).json()["ok"]
        assert _turn(c, "戻ったよ", session_id=yuuka_sid) == eva_sid

    with closing(sqlite3.connect(settings.db_path)) as db:
        rows = db.execute(
            "SELECT content, character_id FROM messages WHERE role='user' ORDER BY rowid"
        ).fetchall()
    assert rows == [("エヴァへの話", "eva"), ("ユウカへの話", "yuuka"), ("戻ったよ", "eva")]


# --- 人格の文を1ファイルに置く(file モード)---

FILE_MODE = "llm:\n  model: eva\n  system_prompt: file\n"


def test_file_mode_sends_persona_file_as_system(tmp_path: Path):
    settings = Settings.load(data_dir=tmp_path)
    root = _pack(settings, "eva", FILE_MODE)
    (root / "persona" / "system.md").write_text("あなたはエヴァです。\n", encoding="utf-8")
    llm = RecordingLLM()
    with TestClient(_app(settings, llm)) as c:
        assert c.post("/v1/characters/eva/activate", headers=H).json()["ok"]
        _turn(c, "ただいま")
    messages = llm.calls[0]
    # 人格の文だけを送る(SENTINEL の土台プロンプトは足さない)
    assert messages[0] == {"role": "system", "content": "あなたはエヴァです。"}
    assert messages[-1] == {"role": "user", "content": "ただいま"}


def test_file_mode_can_point_to_another_file(tmp_path: Path):
    settings = Settings.load(data_dir=tmp_path)
    root = _pack(settings, "eva", FILE_MODE + "  system_file: prompt.txt\n")
    (root / "prompt.txt").write_text("別の場所の人格", encoding="utf-8")
    assert load_pack(root).system_text == "別の場所の人格"


def test_file_mode_without_file_disables_pack(tmp_path: Path):
    settings = Settings.load(data_dir=tmp_path)
    root = _pack(settings, "eva", FILE_MODE)
    pack = load_pack(root)
    assert not pack.valid and "system_file" in (pack.error or "")


def test_file_mode_rejects_path_outside_pack(tmp_path: Path):
    settings = Settings.load(data_dir=tmp_path)
    (settings.characters_dir / "secret.md").write_text("外のファイル", encoding="utf-8")
    root = _pack(settings, "eva", FILE_MODE + "  system_file: ../secret.md\n")
    pack = load_pack(root)
    assert not pack.valid and "Pack の中" in (pack.error or "")


# --- 自己観測ログ ---


def test_turn_log_records_model_persona_and_timing(tmp_path: Path):
    settings = Settings.load(data_dir=tmp_path)
    root = _pack(settings, "eva", FILE_MODE)
    (root / "persona" / "system.md").write_text("あなたはエヴァです。", encoding="utf-8")
    app = _app(settings, RecordingLLM())
    with TestClient(app) as c:
        assert c.post("/v1/characters/eva/activate", headers=H).json()["ok"]
        sid = _turn(c, "ただいま")
        logs = app.state.store.turn_logs(sid)

    assert len(logs) == 1
    log = logs[0]
    assert log["model"] == "eva" and log["character_id"] == "eva"
    assert log["message_id"]  # 保存された返答を指す
    assert len(log["persona_hash"]) == 12
    assert log["prompt_version"]
    assert json.loads(log["recalled_ids"]) == []
    assert log["first_token_ms"] is not None and log["total_ms"] >= log["first_token_ms"]
    assert log["prompt_tokens"] == 42 and log["completion_tokens"] == 7
    assert log["prompt_tokens_est"] > 0 and log["error"] is None


def test_failed_turn_is_logged_with_error(tmp_path: Path):
    settings = Settings.load(data_dir=tmp_path)
    app = _app(settings, OfflineLLM())
    with TestClient(app) as c:
        sid = _turn(c, "やあ")
        logs = app.state.store.turn_logs(sid)
    assert len(logs) == 1
    assert logs[0]["message_id"] is None  # 返答は保存されない
    assert logs[0]["error"] == "(オフライン応答)テスト"
    assert logs[0]["first_token_ms"] is None


def test_usage_is_read_from_last_chunk():
    def handler(req: httpx.Request) -> httpx.Response:
        payload = json.loads(req.content)
        assert payload["stream_options"] == {"include_usage": True}
        lines = [
            f"data: {json.dumps({'choices': [{'delta': {'content': 'ok'}}]})}",
            f"data: {json.dumps({'choices': [], 'usage': {'prompt_tokens': 10, 'completion_tokens': 2}})}",  # noqa: E501
            "data: [DONE]",
        ]
        return httpx.Response(200, text="\n\n".join(lines) + "\n\n")

    async def run() -> tuple[str, dict[str, int] | None]:
        client = OpenAICompatClient("http://llm/v1", "m")
        client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        text = "".join([d async for d in client.stream_chat([{"role": "user", "content": "hi"}])])
        await client.aclose()
        return text, client.last_usage

    assert asyncio.run(run()) == ("ok", {"prompt_tokens": 10, "completion_tokens": 2})


# --- DB 版4 ---


def test_v4_fills_character_id_of_existing_messages(tmp_path: Path, monkeypatch):
    db = tmp_path / "t.db"
    # まず版3までの DB を作り、古い会話を入れておく
    monkeypatch.setattr(store_mod, "MIGRATIONS", store_mod.MIGRATIONS[:3])
    monkeypatch.setattr(store_mod, "SCHEMA_VERSION", 3)
    old = Store(db)
    sid = old.ensure_session(None, "eva")
    with closing(sqlite3.connect(db)) as c, c:
        c.execute(
            "INSERT INTO messages(id,session_id,role,content,created_at) "
            "VALUES('m1',?,'user','古い会話','2026-11-01T00:00:00Z')",
            (sid,),
        )
    monkeypatch.undo()

    store = Store(db)  # 版4を当てる
    assert store.schema_version == 4
    with closing(sqlite3.connect(db)) as c:
        row = c.execute("SELECT character_id FROM messages WHERE id='m1'").fetchone()
    assert row == ("eva",)
    assert (tmp_path / "t.db.bak-v3").exists()  # 移行前の退避


# --- Modelfile の SYSTEM を人格ファイルから作る ---


def _load_build_modelfile() -> Any:
    spec = importlib.util.spec_from_file_location(
        "build_modelfile", REPO / "scripts" / "build_modelfile.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MODELFILE = (
    'FROM gemma4:e4b\nPARAMETER num_ctx 8192\nSYSTEM """古い人格"""\nMESSAGE user """やあ"""\n'
)


def test_render_replaces_only_system_block():
    mod = _load_build_modelfile()
    out = mod.render(MODELFILE, "新しい人格\\n改行あり\n")
    assert 'SYSTEM """新しい人格\\n改行あり"""' in out
    assert "古い人格" not in out
    assert out.startswith("FROM gemma4:e4b\nPARAMETER num_ctx 8192\n")
    assert out.endswith('MESSAGE user """やあ"""\n')  # MESSAGE は残る


def test_render_adds_system_when_missing_and_rejects_triple_quotes():
    mod = _load_build_modelfile()
    out = mod.render("FROM gemma4:e4b\nPARAMETER num_ctx 8192\n", "人格")
    assert out.startswith('FROM gemma4:e4b\n\nSYSTEM """人格"""')
    try:
        mod.render(MODELFILE, 'だめ"""です')
    except ValueError:
        pass
    else:  # pragma: no cover
        raise AssertionError('""" を含む人格の文は止めること')


def test_extract_then_render_round_trips(tmp_path: Path):
    mod = _load_build_modelfile()
    modelfile = tmp_path / "Modelfile"
    modelfile.write_text(MODELFILE, encoding="utf-8")
    system = tmp_path / "eva" / "persona" / "system.md"
    assert mod.main(["--extract", "--system", str(system), "--modelfile", str(modelfile)]) == 0
    assert system.read_text(encoding="utf-8") == "古い人格\n"
    # 既にあるファイルは上書きしない
    assert mod.main(["--extract", "--system", str(system), "--modelfile", str(modelfile)]) == 1
    # 人格の文を書き換えて Modelfile に反映すると、元の内容は .bak に残る
    system.write_text("書き換えた人格\n", encoding="utf-8")
    assert mod.main(["--system", str(system), "--modelfile", str(modelfile)]) == 0
    assert 'SYSTEM """書き換えた人格"""' in modelfile.read_text(encoding="utf-8")
    assert (tmp_path / "Modelfile.bak").read_text(encoding="utf-8") == MODELFILE
