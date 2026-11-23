"""声(読み上げ)の設定・話者一覧・試聴。画面の「設定 → 声」から使う。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from sentinel_core.tts.base import TTSUnavailableError
from sentinel_core.tts.service import speech_payload

router = APIRouter()

PREVIEW_TEXT = "おかえりなさいませ、マスター。今日もお疲れさまでした。"


@router.get("/voice")
async def get_voice(request: Request) -> dict[str, Any]:
    status: dict[str, Any] = await request.app.state.speech.status()
    return status


class VoicePatch(BaseModel):
    enabled: bool | None = None
    # 今のキャラの声(話者・スタイルID)。null を送ると選択を外して Pack / config の既定に戻す
    speaker_id: int | None = None
    clear_speaker: bool = False


@router.patch("/voice")
async def patch_voice(body: VoicePatch, request: Request) -> dict[str, Any]:
    speech = request.app.state.speech
    if body.enabled is not None:
        speech.set_enabled(body.enabled)
    if body.speaker_id is not None or body.clear_speaker:
        speech.set_speaker(None if body.clear_speaker else body.speaker_id)
    status: dict[str, Any] = await speech.status()
    return status


@router.get("/voice/speakers")
async def list_speakers(request: Request) -> dict[str, Any]:
    try:
        return {"speakers": await request.app.state.speech.speakers()}
    except TTSUnavailableError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


class PreviewIn(BaseModel):
    text: str | None = None
    speaker_id: int | None = None  # 省略時は今のキャラの声


@router.post("/voice/preview")
async def preview(body: PreviewIn, request: Request) -> dict[str, Any]:
    """試聴。WAV(base64)と口パクのタイムラインを返す(WS の audio_chunk と同じ形)。"""
    try:
        speech = await request.app.state.speech.preview(
            (body.text or "").strip() or PREVIEW_TEXT, body.speaker_id
        )
    except TTSUnavailableError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    return speech_payload(speech)
