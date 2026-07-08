"""LLMクライアントのポート(抽象)。仕様 §5.2: 上位層は実装名を知らない。"""
from __future__ import annotations

from typing import AsyncIterator, Protocol


class LLMClient(Protocol):
    def stream_chat(self, messages: list[dict]) -> AsyncIterator[str]:
        """messages(OpenAI形式)を受け、応答テキストのデルタを順に返す。"""
        ...

    async def is_reachable(self) -> bool:
        """推論サーバーの死活(/v1/system/health が参照)。"""
        ...
