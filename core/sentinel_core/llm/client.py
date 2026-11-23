"""LLMクライアントのポート(抽象)。仕様 §5.2: 上位層は実装名を知らない。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

# OpenAI形式のチャットメッセージ({"role": ..., "content": ...})
Message = dict[str, str]


class LLMUnavailableError(Exception):
    """推論サーバーに接続できない・エラーを返した。

    メッセージはそのままユーザーに見せる案内文。モデルの発言ではないので、
    会話履歴には保存しない(次のターンでLLMに渡ると、記憶を汚すため)。
    """


class LLMClient(Protocol):
    def stream_chat(
        self, messages: list[Message], *, model: str | None = None
    ) -> AsyncIterator[str]:
        """messages(OpenAI形式)を受け、応答テキストのデルタを順に返す。

        model を渡すとこのターンだけそのモデルを使う(Character Pack がモデルを
        指定したとき。例: Ollama の `eva`)。None なら設定の llm.chat_model。

        推論サーバーが使えないときは LLMUnavailableError を送出する。
        """
        ...

    async def is_reachable(self) -> bool:
        """推論サーバーの死活(/v1/system/health が参照)。"""
        ...
