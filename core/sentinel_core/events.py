"""WSイベントハブ(仕様 §7 のWSイベント契約)。

- server→client イベントを全接続へファンアウトする最小pubsub
- イベント型は `type` の追加のみ許可(既存フィールドの削除・意味変更は禁止)
- `approval_required` はPhase 2(承認ゲート)用に型だけ予約
"""

from __future__ import annotations

import asyncio
from typing import Any

# 購読キューの終端通知。受け取った側は購読を打ち切る(=WSを閉じて再接続させる)
CLOSE_SENTINEL = None

# 購読キューの要素: イベント辞書 or 終端通知(CLOSE_SENTINEL)
EventQueue = asyncio.Queue["dict[str, Any] | None"]


class EventHub:
    def __init__(self) -> None:
        self._subscribers: set[EventQueue] = set()

    def subscribe(self) -> EventQueue:
        q: EventQueue = asyncio.Queue(maxsize=1024)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: EventQueue) -> None:
        self._subscribers.discard(q)

    async def publish(self, event: dict[str, Any]) -> None:
        for q in list(self._subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                # 詰まったクライアントは切り離す(全体を止めない)。
                # 読み手が q.get() で永久に待たないよう、空けて終端通知を入れる。
                self._subscribers.discard(q)
                while not q.empty():
                    q.get_nowait()
                q.put_nowait(CLOSE_SENTINEL)
