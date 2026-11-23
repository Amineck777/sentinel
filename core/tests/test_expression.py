"""感情タグの抜き取りと、言葉からの表情の推測(expression.py)。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi.testclient import TestClient

from sentinel_core.api.app import create_app
from sentinel_core.expression import Tag, TagFilter, TurnExpression, guess_emotion
from sentinel_core.settings import Settings

TOKEN = "test-token"
H = {"X-Sentinel-Token": TOKEN}


def run_filter(deltas: list[str]) -> tuple[str, list[str]]:
    f = TagFilter()
    text, tags = "", []
    for d in deltas:
        for item in f.feed(d):
            if isinstance(item, Tag):
                tags.append(str(item))
            else:
                text += item
    return text + f.flush(), tags


def test_tags_are_removed_even_when_split_across_tokens():
    assert run_filter(["[jo", "y] はい。", "［sorrow］残念です"]) == (
        "はい。残念です",
        ["joy", "sorrow"],
    )


def test_unknown_brackets_and_long_text_stay():
    assert run_filter(["[メモ]と", "[リンク](http://x)"]) == ("[メモ]と[リンク](http://x)", [])
    assert run_filter(["配列は a[0", "] です"]) == ("配列は a[0] です", [])
    # 閉じないまま終わった [ も消さずに返す
    assert run_filter(["最後に ["]) == ("最後に [", [])


def test_aliases():
    assert run_filter(["[Happy]やった"]) == ("やった", ["joy"])


def test_guess_takes_first_cue():
    assert guess_emotion("お帰りなさいませ。") == "neutral"
    assert guess_emotion("申し訳ありません、でも嬉しいです") == "sorrow"
    assert guess_emotion("それは良かったです") == "joy"
    assert guess_emotion("まあ、そうでしたか") == "surprised"


def test_explicit_tag_wins_and_persists_until_next():
    t = TurnExpression()
    got: list[tuple[str, str]] = []
    for d in ["[fun]嬉しいです。", "次の文です。", "[neutral]", "以上です"]:
        got += t.feed(d)[1]
    got += t.flush()[1]
    assert got == [("嬉しいです。", "fun"), ("次の文です。", "fun"), ("以上です", "neutral")]


class TaggedLLM:
    async def stream_chat(self, messages, *, model=None) -> AsyncIterator[str]:
        for chunk in ["[jo", "y]お帰りなさいませ。", "心配しておりました"]:
            await asyncio.sleep(0)
            yield chunk

    async def is_reachable(self) -> bool:
        return True


def test_chat_strips_tags_and_sends_emotion_events(tmp_path: Path):
    settings = Settings.load(data_dir=tmp_path)
    app = create_app(settings=settings, token=TOKEN, dev=True, llm=TaggedLLM())
    with TestClient(app) as c, c.websocket_connect(f"/v1/stream?token={TOKEN}") as ws:
        c.post("/v1/chat", headers=H, json={"content": "ただいま"})
        events = []
        while not events or events[-1]["type"] != "message_done":
            events.append(ws.receive_json())
    text = "".join(e["delta"] for e in events if e["type"] == "token")
    assert text == "お帰りなさいませ。心配しておりました"
    # タグ(joy)は次のタグまで続くので、推測(心配=sorrow)より優先される
    assert [e["emotion"] for e in events if e["type"] == "emotion"] == ["joy"]
