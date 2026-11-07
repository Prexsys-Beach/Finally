"""Shared route dependencies and validation."""

from __future__ import annotations

import sqlite3
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request

from ..db import connect
from ..market import MarketDataSource, PriceCache
from ..watchlist import validate_ticker


def ticker_path(ticker: str) -> str:
    try:
        return validate_ticker(ticker)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


async def get_db(request: Request) -> AsyncIterator[sqlite3.Connection]:
    # async so that the connection is opened on the thread that uses it
    conn = connect(request.app.state.db_path)
    try:
        yield conn
    finally:
        conn.close()


def get_cache(request: Request) -> PriceCache:
    return request.app.state.price_cache


def get_source(request: Request) -> MarketDataSource:
    return request.app.state.market_source


Db = Annotated[sqlite3.Connection, Depends(get_db)]
Cache = Annotated[PriceCache, Depends(get_cache)]
Source = Annotated[MarketDataSource, Depends(get_source)]
TickerPath = Annotated[str, Depends(ticker_path)]
