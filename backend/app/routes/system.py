"""System endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from .deps import Cache, Db, Source

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health")
async def health(db: Db, cache: Cache, source: Source) -> dict:
    db.execute("SELECT 1")
    return {
        "status": "ok",
        "market_data": {
            "mode": source.mode,
            "tracked_tickers": len(source.get_tickers()),
            "priced_tickers": len(cache),
        },
    }
