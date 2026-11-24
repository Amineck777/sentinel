"""OpenAI互換エンドポイント(Ollama等)へのストリーミングクライアント。

設計判断: 推論サーバー未起動でもコアとUIの開発を止めないため、接続失敗時は
案内文(オフライン応答)を LLMUnavailableError で返す(実装方針 §4)。配布版でも
「Ollamaが落ちている」状態をユーザーに文章で伝えられる。案内文はモデルの発言では
ないので、ChatService が履歴に保存せず通知として表示する。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from sentinel_core.llm.client import LLMUnavailableError, Message

OFFLINE_NOTICE = (
    "(オフライン応答)推論サーバーに接続できませんでした。"
    "Ollama が起動しているか、設定の llm.endpoint を確認してください。"
    "接続後はこのメッセージの代わりにモデルの応答が返ります。"
)


class OpenAICompatClient:
    def __init__(
        self, endpoint: str, model: str, timeout_sec: int = 120, think: bool = False
    ) -> None:
        self._endpoint = endpoint  # 例: http://127.0.0.1:11434/v1
        self._model = model
        # think=False のとき、思考を切る指定(reasoning_effort="none")を送る。
        # Ollama は OpenAI 互換 API でこれを think=false として扱う。対応していない
        # サーバーが 400 を返したら、以後は送らない(_send_reasoning_off を倒す)
        self._send_reasoning_off = not think
        # 返答の最後にトークン数(usage)を返してもらう指定。自己観測ログ用(ADR 0116)。
        # 受け付けないサーバーでは、思考オフの指定と一緒に外してやり直す
        self._send_usage = True
        # 直前の stream_chat で受け取ったトークン数({"prompt_tokens", "completion_tokens"})。
        # サーバーが返さなければ None。生成はセッションごとに直列なので、呼んだ直後に読めばよい
        self.last_usage: dict[str, int] | None = None
        # 接続は使い回す(リクエスト毎のクライアント生成はハンドシェイクコストが無駄)
        self._client = httpx.AsyncClient(timeout=timeout_sec)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def stream_chat(
        self, messages: list[Message], *, model: str | None = None
    ) -> AsyncIterator[str]:
        use_model = model or self._model
        self.last_usage = None  # 前のターンの値を残さない
        try:
            try:
                async for delta in self._stream(messages, use_model):
                    yield delta
            except httpx.HTTPStatusError as e:
                # 思考オフや usage の指定を受け付けないサーバー(古い Ollama 等)。
                # どちらが原因かは分からないので両方外して1回だけやり直す。
                # 応答は raise_for_status で止まるので、まだ1文字も返していない
                if e.response.status_code != 400 or not (
                    self._send_reasoning_off or self._send_usage
                ):
                    raise
                self._send_reasoning_off = False
                self._send_usage = False
                async for delta in self._stream(messages, use_model):
                    yield delta
        except httpx.TransportError as e:  # 接続不可・切断・タイムアウト → オフライン応答
            raise LLMUnavailableError(OFFLINE_NOTICE) from e
        except httpx.HTTPStatusError as e:  # 接続はできたがエラー(モデル名違い等)
            raise LLMUnavailableError(
                f"(推論サーバーエラー: HTTP {e.response.status_code})"
                f"モデル名 '{use_model}' が存在するか確認してください"
                "(キャラの character.yaml の llm.model、または設定の llm.chat_model)。"
            ) from e

    async def _stream(self, messages: list[Message], model: str) -> AsyncIterator[str]:
        url = f"{self._endpoint}/chat/completions"
        payload: dict[str, Any] = {"model": model, "messages": messages, "stream": True}
        if self._send_reasoning_off:
            payload["reasoning_effort"] = "none"
        if self._send_usage:
            payload["stream_options"] = {"include_usage": True}
        async with self._client.stream("POST", url, json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[len("data:") :].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                # usage は最後のチャンク(choices が空)に来る
                usage = chunk.get("usage") if isinstance(chunk, dict) else None
                if isinstance(usage, dict):
                    self.last_usage = {
                        "prompt_tokens": int(usage.get("prompt_tokens") or 0),
                        "completion_tokens": int(usage.get("completion_tokens") or 0),
                    }
                try:
                    # 思考モデルの思考は delta.reasoning に来る。返答(content)だけを使う
                    delta = chunk["choices"][0]["delta"].get("content")
                except (KeyError, IndexError, TypeError):
                    continue
                if delta:
                    yield delta

    async def is_reachable(self) -> bool:
        try:
            r = await self._client.get(f"{self._endpoint}/models", timeout=3)
            return r.status_code < 500
        except httpx.HTTPError:
            return False
