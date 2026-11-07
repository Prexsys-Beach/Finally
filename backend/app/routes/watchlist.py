"""Watchlist endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, field_validator

from .. import watchlist
from .deps import Cache, Db, Source, TickerPath, validate_ticker

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])


class WatchlistAdd(BaseModel):
    ticker: str

    _normalize = field_validator("ticker")(validate_ticker)


@router.get("")
async def get_watchlist(db: Db, cache: Cache) -> dict:
    return {"tickers": watchlist.get_watchlist(db, cache)}


@router.post("", status_code=201)
async def add_ticker(body: WatchlistAdd, db: Db, cache: Cache, source: Source) -> dict:
    try:
        await watchlist.add_to_watchlist(db, source, body.ticker)
    except watchlist.DuplicateTickerError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return {"tickers": watchlist.get_watchlist(db, cache)}


@router.delete("/{ticker}", status_code=204)
async def remove_ticker(ticker: TickerPath, db: Db, source: Source) -> Response:
    try:
        await watchlist.remove_from_watchlist(db, source, ticker)
    except watchlist.TickerNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return Response(status_code=204)
