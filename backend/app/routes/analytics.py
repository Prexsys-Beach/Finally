"""Analytics endpoints: indicators per ticker, portfolio risk, and forecasts."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, Request

from ..analytics import service
from ..market.bars import Timeframe
from .deps import Cache, Db, Source, TickerPath, validate_ticker

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
    request: Request,
    db: Db,
    cache: Cache,
    source: Source,
    timeframe: Literal["1m", "1d"] = "1d",
) -> dict:
    """Risk of the current positions: volatility, beta, VaR, concentration, correlations."""
    return service.portfolio_analytics(
        db, cache, timeframe, _retention_days(request), mode=source.mode
    )


Horizon = Literal["1h", "1d", "1w"]  # The keys of analytics.forecast.HORIZONS


@router.get("/forecast")
async def forecast(
    request: Request,
    db: Db,
    cache: Cache,
    source: Source,
    target: str = "portfolio",
    horizon: Horizon = "1d",
    level: Annotated[float | None, Query(gt=0)] = None,
) -> dict:
    """Monte Carlo percentile bands for the portfolio's value or a ticker's price."""
    if target.lower() != "portfolio":
        try:
            target = validate_ticker(target)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
    else:
        target = "portfolio"
    try:
        return service.forecast(
            db, cache, target, horizon, _retention_days(request), mode=source.mode, level=level
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
