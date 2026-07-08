"""OpenAI互換エンドポイント(Ollama等)へのストリーミングクライアント。

設計判断: 推論サーバー未起動でもコアとUIの開発を止めないため、接続失敗時は
オフライン応答へフォールバックする(実装方針 §4)。配布版でも「Ollamaが落ちて
いる」状態をユーザーに文章で伝えられる。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from sentinel_core.llm.client import Message

OFFLINE_NOTICE = (
    "(オフライン応答)推論サーバーに接続できませんでした。"
    "Ollama が起動しているか、設定の llm.endpoint を確認してください。"
    "接続後はこのメッセージの代わりにモデルの応答が返ります。"
)


class OpenAICompatClient:
    def __init__(self, endpoint: str, model: str, timeout_sec: int = 120) -> None:
        self._endpoint = endpoint  # 例: http://127.0.0.1:11434/v1
        self._model = model
        # 接続は使い回す(リクエスト毎のクライアント生成はハンドシェイクコストが無駄)
        self._client = httpx.AsyncClient(timeout=timeout_sec)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def stream_chat(self, messages: list[Message]) -> AsyncIterator[str]:
        url = f"{self._endpoint}/chat/completions"
        payload: dict[str, Any] = {"model": self._model, "messages": messages, "stream": True}
        try:
            async with self._client.stream("POST", url, json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[len("data:") :].strip()
                    if data == "[DONE]":
                        break
                    try:
                        delta = json.loads(data)["choices"][0]["delta"].get("content")
                    except (KeyError, IndexError, json.JSONDecodeError):
                        continue
                    if delta:
                        yield delta
        except httpx.TransportError:  # 接続不可・切断・タイムアウト → オフライン応答
            yield OFFLINE_NOTICE
        except httpx.HTTPStatusError as e:  # 接続はできたがエラー(モデル名違い等)
            yield (
                f"(推論サーバーエラー: HTTP {e.response.status_code})"
                f"モデル名 '{self._model}' が存在するか、設定の llm.chat_model を確認してください。"
            )

    async def is_reachable(self) -> bool:
        try:
            r = await self._client.get(f"{self._endpoint}/models", timeout=3)
            return r.status_code < 500
        except httpx.HTTPError:
            return False
