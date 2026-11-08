"""History providers: fill in past bars before live recording began.

SyntheticHistory makes up history with the simulator's own model, so charts and
calculations have data on first launch. MassiveHistory fetches real bars. A
purchased data feed would be one more HistoryProvider.
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from typing import ClassVar

import numpy as np
from massive import RESTClient
from massive.exceptions import BadResponse
from massive.rest.models import Agg

from .bars import TIMEFRAME_SECONDS, Bar, Origin, bucket_start
from .simulator import GBMSimulator, correlation_matrix, ticker_params

logger = logging.getLogger(__name__)

EVENT_SIZE = (0.02, 0.05)  # Jumps move a price 2-5%, as in the live simulator


@dataclass(frozen=True, slots=True)
class BarModel:
    """How much trading time one bar covers, and how many jumps to expect in it."""

    trading_seconds: float
    events: float
    substeps: int  # Price steps per bar, so highs and lows are realistic


TRADING_DAY_SECONDS = 6.5 * 3600
EVENTS_PER_TRADING_DAY = 0.05  # About one jump a month


def _model(trading_seconds: float, substeps: int) -> BarModel:
    events = EVENTS_PER_TRADING_DAY * trading_seconds / TRADING_DAY_SECONDS
    return BarModel(trading_seconds, events, substeps)


# Synthetic history looks like a real stock: the simulator's drift, volatility and
# correlations, with an occasional jump. It deliberately doesn't copy the live
# simulator's jump rate (a 0.1% chance per ticker per 0.5s tick, about 170 jumps
# a day), which keeps the live demo lively but compounds to absurd prices over
# days of history. A one-minute bar is a minute of trading time, as live; a daily
# bar is one 6.5-hour trading day.
BAR_MODELS: dict[str, BarModel] = {
    "1m": _model(60, substeps=12),
    "1d": _model(TRADING_DAY_SECONDS, substeps=78),
}


MASSIVE_CALL_SPACING_SECONDS = 12.5  # Stays within 5 requests/minute
MASSIVE_TIMESPAN = {"1m": "minute", "1d": "day"}
MASSIVE_PAGE_LIMIT = 50000


@dataclass(frozen=True, slots=True)
class BackfillRequest:
    """Bars wanted for [start, end), both on bucket boundaries.

    anchor is the price the history must lead into: the open of the earliest
    stored bar, or the current price if nothing is stored. Providers of real data
    ignore it.
    """

    ticker: str
    timeframe: str
    start: int
    end: int
    anchor: float | None


class HistoryProvider(ABC):
    origin: ClassVar[Origin]

    @abstractmethod
    async def fetch(self, requests: Sequence[BackfillRequest]) -> list[Bar]:
        """Bars for the requests. Missing data is skipped, not an error."""


def simulate_ohlc(
    tickers: Sequence[str],
    n_bars: int,
    timeframe: str,
    rng: np.random.Generator,
    events_per_bar: float | None = None,
) -> np.ndarray:
    """Correlated OHLC paths from the simulator's GBM model, starting at 1.0.

    Returns shape (n_bars, len(tickers), 4): open, high, low, close. The timeframe's
    BarModel sets the time each bar covers and, unless given, the jump rate.
    """
    model = BAR_MODELS[timeframe]
    events = model.events if events_per_bar is None else events_per_bar
    k = len(tickers)
    steps = model.substeps
    dt = model.trading_seconds / steps / GBMSimulator.TRADING_SECONDS_PER_YEAR
    params = [ticker_params(t) for t in tickers]
    mu = np.array([p["mu"] for p in params])
    sigma = np.array([p["sigma"] for p in params])
    n_steps = n_bars * steps

    z = rng.standard_normal((n_steps, k)) @ np.linalg.cholesky(correlation_matrix(list(tickers))).T
    log_returns = (mu - 0.5 * sigma**2) * dt + sigma * np.sqrt(dt) * z

    counts = rng.poisson(events / steps, (n_steps, k))
    for n in range(1, int(counts.max(initial=0)) + 1):
        size = rng.uniform(*EVENT_SIZE, (n_steps, k))
        sign = rng.choice([-1.0, 1.0], (n_steps, k))
        log_returns += np.where(counts >= n, np.log1p(sign * size), 0.0)

    path = np.exp(np.vstack([np.zeros((1, k)), np.cumsum(log_returns, axis=0)]))
    within = path[1:].reshape(n_bars, steps, k)
    opens = path[:-1:steps]
    closes = within[:, -1, :]
    highs = np.maximum(within.max(axis=1), opens)
    lows = np.minimum(within.min(axis=1), opens)
    return np.stack([opens, highs, lows, closes], axis=-1)


class SyntheticHistory(HistoryProvider):
    """Made-up past bars that end exactly at each request's anchor price.

    Requests with the same timeframe and range are generated together, so tickers
    keep the simulator's correlations. Requests without an anchor are skipped.
    """

    origin = "synthetic"

    def __init__(self, seed: int | None = None) -> None:
        self._rng = np.random.default_rng(seed)

    async def fetch(self, requests: Sequence[BackfillRequest]) -> list[Bar]:
        return await asyncio.to_thread(self.generate, requests)

    def generate(self, requests: Sequence[BackfillRequest]) -> list[Bar]:
        groups: dict[tuple[str, int, int], list[BackfillRequest]] = defaultdict(list)
        for request in requests:
            if request.anchor and request.end > request.start:
                groups[(request.timeframe, request.start, request.end)].append(request)

        bars: list[Bar] = []
        for (timeframe, start, end), group in groups.items():
            seconds = TIMEFRAME_SECONDS[timeframe]
            n_bars = (end - start) // seconds
            if n_bars <= 0:
                continue
            tickers = [r.ticker for r in group]
            ohlc = simulate_ohlc(tickers, n_bars, timeframe, self._rng)
            ohlc *= (
                np.array([r.anchor for r in group])[None, :, None] / ohlc[-1, :, 3][None, :, None]
            )
            ohlc = np.round(ohlc, 2)
            for i in range(n_bars):
                for j, ticker in enumerate(tickers):
                    o, h, lo, c = ohlc[i, j]
                    bars.append(
                        Bar(ticker, timeframe, start + i * seconds, o, h, lo, c, "synthetic")
                    )
        return bars


def _positive(value: float | None) -> bool:
    return value is not None and value > 0


class MassiveHistory(HistoryProvider):
    """Real bars from Massive's aggregates endpoint, one call per request.

    Calls are spaced to fit the free plan's rate limit. Requests the plan can't
    serve, or that fail, are skipped and logged.
    """

    origin = "vendor"

    def __init__(self, api_key: str, call_spacing: float = MASSIVE_CALL_SPACING_SECONDS) -> None:
        self._client = RESTClient(api_key=api_key, retries=0)
        self._spacing = call_spacing

    async def fetch(self, requests: Sequence[BackfillRequest]) -> list[Bar]:
        bars: list[Bar] = []
        wanted = [r for r in requests if r.end > r.start]
        for i, request in enumerate(wanted):
            if i:
                await asyncio.sleep(self._spacing)
            try:
                aggs = await asyncio.to_thread(self._list_aggs, request)
            except BadResponse as e:
                logger.warning("Massive history unavailable for %s: %s", request.ticker, e)
                continue
            except Exception as e:
                logger.warning("Massive history failed for %s: %r", request.ticker, e)
                continue
            bars += self.to_bars(request, aggs)
        return bars

    def _list_aggs(self, request: BackfillRequest) -> list[Agg]:
        return list(
            self._client.list_aggs(
                request.ticker,
                1,
                MASSIVE_TIMESPAN[request.timeframe],
                request.start * 1000,
                request.end * 1000 - 1,
                adjusted=True,
                sort="asc",
                limit=MASSIVE_PAGE_LIMIT,
            )
        )

    @staticmethod
    def to_bars(request: BackfillRequest, aggs: Sequence[Agg]) -> list[Bar]:
        """Bars within the request. Daily bars start at US midnight; move them to UTC."""
        bars: dict[int, Bar] = {}
        for agg in aggs:
            prices = (agg.open, agg.high, agg.low, agg.close)
            if not agg.timestamp or not all(map(_positive, prices)):
                continue
            start = bucket_start(agg.timestamp / 1000, request.timeframe)
            if request.start <= start < request.end:
                bars[start] = Bar(request.ticker, request.timeframe, start, *prices, "vendor")
        return [bars[start] for start in sorted(bars)]
