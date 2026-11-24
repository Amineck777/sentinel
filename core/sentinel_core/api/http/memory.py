"""長期記憶の確認用 API(ADR 0116 の PR2)。

画面(歯車 → 記憶)は PR4 で作る。それまでは、ここを直接呼んで中身を確かめる。
- GET  /v1/memory/facts     有効な事実(?all=true で置き換え済み・忘れたものも)
- GET  /v1/memory/episodes  出来事(?character_id=eva でそのキャラの分だけ)
- GET  /v1/memory/jobs      記憶づくりの記録(新しい順)
- GET  /v1/memory/search    キーワード検索(?q=...&character_id=...)
- POST /v1/memory/extract   区切りを待たずに、今すぐ記憶を作る
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/memory/facts")
async def list_facts(request: Request, all: bool = False) -> dict[str, Any]:
    return {"facts": request.app.state.longterm.list_facts(include_inactive=all)}


@router.get("/memory/episodes")
async def list_episodes(request: Request, character_id: str | None = None) -> dict[str, Any]:
    lt = request.app.state.longterm
    if character_id is None:
        return {"episodes": lt.list_episodes()}
    # "none" は汎用モード(キャラ ID が無い)の出来事
    cid = None if character_id == "none" else character_id
    return {"episodes": lt.list_episodes(cid, any_character=False)}


@router.get("/memory/jobs")
async def list_jobs(request: Request) -> dict[str, Any]:
    return {"jobs": request.app.state.longterm.list_jobs()}


@router.get("/memory/search")
async def search(request: Request, q: str, character_id: str | None = None) -> dict[str, Any]:
    # character_id を省いたら、今のキャラとして探す(チャットで思い出すときと同じ条件)
    cid = request.app.state.characters.active_id if character_id is None else character_id
    cid = None if cid == "none" else cid
    hits = request.app.state.longterm.search_keyword(q, cid)
    return {"hits": [asdict(h) for h in hits]}


@router.post("/memory/extract")
async def extract_now(request: Request) -> dict[str, Any]:
    """今すぐ記憶を作る(終わるまで待って件数を返す)。チャットの生成中は何もしない。"""
    return {"result": await request.app.state.memory.run_pending()}
