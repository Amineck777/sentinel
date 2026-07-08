"""チャットAPI(仕様 §7)。ルーターは受付のみ。生成は agent.service.ChatService の責務。"""
from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter()


class ChatIn(BaseModel):
    content: str
    session_id: str | None = None
    character_id: str | None = None  # 指定時はこのターンから切替


class ChatOut(BaseModel):
    session_id: str
    message_id: str


@router.post("/chat", response_model=ChatOut)
async def post_chat(body: ChatIn, request: Request) -> ChatOut:
    sid, mid = request.app.state.chat.start_turn(
        content=body.content,
        session_id=body.session_id,
        character_id=body.character_id,
    )
    return ChatOut(session_id=sid, message_id=mid)


@router.get("/sessions")
async def list_sessions(request: Request) -> dict:
    return {"sessions": request.app.state.store.list_sessions()}
