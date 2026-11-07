"""Portfolio endpoints."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from .. import portfolio
from .deps import Cache, Db, Source, validate_ticker

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


class TradeRequest(BaseModel):
    ticker: str
    quantity: float = Field(gt=0, allow_inf_nan=False)
    side: Literal["buy", "sell"]

    _normalize = field_validator("ticker")(validate_ticker)


@router.get("")
async def get_portfolio(db: Db, cache: Cache) -> dict:
    return portfolio.get_portfolio(db, cache)


@router.post("/trade")
async def trade(body: TradeRequest, db: Db, cache: Cache, source: Source) -> dict:
    try:
        executed = await portfolio.place_trade(
            db, cache, source, body.ticker, body.side, body.quantity
        )
    except portfolio.PriceUnavailableError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except portfolio.TradeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"trade": executed, "portfolio": portfolio.get_portfolio(db, cache)}


@router.get("/history")
async def history(
    db: Db, limit: Annotated[int, Query(ge=1, le=10000)] = 1000
) -> dict:
    return {"snapshots": portfolio.get_history(db, limit)}
