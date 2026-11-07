"""Chat endpoint."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import chat
from .deps import Cache, Db, Source

router = APIRouter(prefix="/api", tags=["chat"])


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


@router.get("/chat")
async def get_chat(db: Db) -> dict:
    return {"messages": chat.get_messages(db)}


@router.post("/chat")
async def post_chat(body: ChatRequest, db: Db, cache: Cache, source: Source) -> dict:
    try:
        return await chat.handle_chat(db, cache, source, body.message)
    except chat.ChatError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
