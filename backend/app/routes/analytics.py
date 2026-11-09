"""Analytics endpoints: indicators, portfolio risk, forecasts and backtests."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator

from ..analytics import service
from ..analytics.backtest import STRATEGIES, BacktestError
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


class BacktestRequest(BaseModel):
    ticker: str
    strategy: Literal["buy_and_hold", "sma_crossover", "rsi_reversion"] = "sma_crossover"
    params: dict = Field(default_factory=dict)
    timeframe: Timeframe = "1d"
    start: int | None = Field(default=None, ge=0, description="Unix seconds")
    end: int | None = Field(default=None, ge=0, description="Unix seconds")
    slippage_bps: float = Field(default=0.0, ge=0, le=100)

    _normalize = field_validator("ticker")(validate_ticker)


@router.get("/backtest/strategies")
async def strategies() -> dict:
    """The strategies a backtest can run."""
    return {"strategies": {key: label for key, (label, _) in STRATEGIES.items()}}


@router.post("/backtest")
async def backtest(request: Request, body: BacktestRequest, db: Db) -> dict:
    """Replay a strategy on stored bars: returns, drawdown, trades and the equity curve.

    A decision made at one bar's close is carried out at the next bar's close.
    """
    try:
        return service.backtest(
            db,
            body.ticker,
            body.strategy,
            body.params,
            body.timeframe,
            _retention_days(request),
            start=body.start,
            end=body.end,
            slippage_bps=body.slippage_bps,
        )
    except BacktestError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
