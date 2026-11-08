"""Market history endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from ..market.bars import Timeframe, recent_bars
from .deps import Db, TickerPath

router = APIRouter(prefix="/api/market", tags=["market"])


@router.get("/bars/{ticker}")
async def bars(
    ticker: TickerPath,
    db: Db,
    timeframe: Timeframe = "1m",
    limit: Annotated[int, Query(ge=1, le=10000)] = 500,
) -> dict:
    """The most recent bars, oldest first. Each says whether it is real or synthetic."""
    return {
        "ticker": ticker,
        "timeframe": timeframe,
        "bars": [bar.to_dict() for bar in recent_bars(db, ticker, timeframe, limit)],
    }
