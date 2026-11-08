"""Analytics endpoints: indicators per ticker, risk for the portfolio."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Query, Request

from ..analytics import service
from ..market.bars import Timeframe
from .deps import Cache, Db, TickerPath

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


def _retention_days(request: Request) -> float:
    return request.app.state.history.retention_days


@router.get("/ticker/{ticker}")
async def ticker(
    request: Request,
    ticker: TickerPath,
    db: Db,
    timeframe: Timeframe = "1m",
    limit: Annotated[int, Query(ge=1, le=10000)] = 500,
) -> dict:
    """Indicators over the last `limit` bars: latest values, signals and series."""
    return service.ticker_analytics(db, ticker, timeframe, limit, _retention_days(request))


@router.get("/portfolio")
async def portfolio(
    request: Request, db: Db, cache: Cache, timeframe: Literal["1m", "1d"] = "1d"
) -> dict:
    """Risk of the current positions: volatility, beta, VaR, concentration, correlations."""
    return service.portfolio_analytics(db, cache, timeframe, _retention_days(request))
