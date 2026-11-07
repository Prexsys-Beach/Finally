"""Massive (formerly Polygon.io) API client for real market data."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta

from massive import RESTClient
from massive.exceptions import BadResponse
from massive.rest.models import GroupedDailyAgg, TickerSnapshot

from .cache import PriceCache
from .interface import DataMode, MarketDataSource, normalize_ticker

logger = logging.getLogger(__name__)

EOD_REFRESH_SECONDS = 3600.0  # End-of-day data changes once a day
EOD_LOOKBACK_DAYS = 10  # Far enough to cross any US market holiday run
EOD_CALL_SPACING_SECONDS = 12.5  # Stays within 5 requests/minute
CLOSES_RETRY_SECONDS = 60.0  # Wait after a failed load, so a bad spell costs few calls
CLOSES_LOAD_TIMEOUT_SECONDS = 20.0  # Startup waits on this, so it must stay short

DailyClose = tuple[float, float | None, float]  # close, previous close, timestamp


def _positive(value: float | None) -> float | None:
    """Return value if it is a usable price; Massive can send 0 or omit fields."""
    return value if value is not None and value > 0 else None


def snapshot_price(snap: TickerSnapshot) -> float | None:
    """Best available price, freshest first. lastTrade is plan-dependent."""
    candidates = (
        snap.last_trade.price if snap.last_trade else None,
        snap.min.close if snap.min else None,
        snap.day.close if snap.day else None,
        snap.prev_day.close if snap.prev_day else None,
    )
    return next((p for p in map(_positive, candidates) if p is not None), None)


def snapshot_timestamp(snap: TickerSnapshot) -> float | None:
    """Unix seconds. lastTrade.t and updated are nanoseconds, min.t is milliseconds."""
    if snap.last_trade and snap.last_trade.sip_timestamp:
        return snap.last_trade.sip_timestamp / 1e9
    if snap.updated:
        return snap.updated / 1e9
    if snap.min and snap.min.timestamp:
        return snap.min.timestamp / 1e3
    return None


def snapshot_previous_close(snap: TickerSnapshot) -> float | None:
    return _positive(snap.prev_day.close) if snap.prev_day else None


def _is_plan_limit(error: BadResponse) -> bool:
    """HTTP 403. BadResponse carries only the body, so match on its status."""
    return "NOT_AUTHORIZED" in str(error)


async def _fetch_grouped_day(client: RESTClient, day: date) -> list[GroupedDailyAgg]:
    """Bars for one date; empty if it is a holiday or too recent for the plan."""
    try:
        return await asyncio.to_thread(
            client.get_grouped_daily_aggs, day.isoformat(), adjusted=True
        )
    except BadResponse as e:
        if _is_plan_limit(e):
            return []
        raise


async def _latest_sessions(client: RESTClient, spacing: float) -> list[list[GroupedDailyAgg]]:
    """Walk back from today to the two most recent sessions with data.

    A failure after the first session keeps it: a close is useful without the
    previous one, which only feeds the daily change.
    """
    sessions: list[list[GroupedDailyAgg]] = []
    today = datetime.now(UTC).date()
    for offset in range(EOD_LOOKBACK_DAYS):
        day = today - timedelta(days=offset)
        if day.weekday() >= 5:
            continue
        try:
            bars = await _fetch_grouped_day(client, day)
        except Exception as e:
            if not sessions:
                raise
            logger.warning("Massive: kept the latest session, older one failed: %s", e)
            break
        if bars:
            sessions.append(bars)
        if len(sessions) == 2:
            break
        await asyncio.sleep(spacing)
    return sessions


def _closes_by_ticker(sessions: Sequence[list[GroupedDailyAgg]]) -> dict[str, DailyClose]:
    if not sessions:
        return {}
    previous = {b.ticker: b.close for b in sessions[1]} if len(sessions) > 1 else {}
    return {
        bar.ticker: (bar.close, previous.get(bar.ticker), bar.timestamp / 1e3)
        for bar in sessions[0]
        if _positive(bar.close) and bar.timestamp
    }


class DailyCloses:
    """The latest real close of every US stock, kept in memory.

    One grouped call covers the whole market, so adding a ticker costs no request
    until the data is due for a refresh.
    """

    def __init__(
        self,
        api_key: str,
        refresh_seconds: float = EOD_REFRESH_SECONDS,
        timeout: float = CLOSES_LOAD_TIMEOUT_SECONDS,
    ) -> None:
        self._client = RESTClient(api_key=api_key, retries=0)
        self._refresh_seconds = refresh_seconds
        self._timeout = timeout
        self._closes: dict[str, DailyClose] = {}
        self._next_load = 0.0

    async def load(self) -> dict[str, DailyClose]:
        """Current closes, fetched if due. Keeps the last good set if a fetch fails."""
        if time.monotonic() < self._next_load:
            return self._closes
        try:
            sessions = await asyncio.wait_for(
                _latest_sessions(self._client, spacing=0), self._timeout
            )
            closes = _closes_by_ticker(sessions)
        except Exception as e:
            logger.warning("Massive: could not load real closes: %r", e)
            closes = {}
        if closes:
            self._closes = closes
        delay = self._refresh_seconds if closes else CLOSES_RETRY_SECONDS
        self._next_load = time.monotonic() + delay
        return self._closes


class MassiveDataSource(MarketDataSource):
    """MarketDataSource backed by the Massive REST API.

    live: polls the snapshot endpoint, one call for all tickers.
    eod:  the key's plan has no snapshot access (HTTP 403), so publish the latest
          daily closes from the grouped daily endpoint and refresh hourly.
    """

    def __init__(
        self,
        api_key: str,
        price_cache: PriceCache,
        poll_interval: float = 15.0,
        eod_call_spacing: float = EOD_CALL_SPACING_SECONDS,
    ) -> None:
        self._api_key = api_key
        self._cache = price_cache
        self._interval = poll_interval
        self._eod_call_spacing = eod_call_spacing
        self._tickers: list[str] = []
        self._task: asyncio.Task | None = None
        self._client: RESTClient | None = None
        self._mode: DataMode = "live"
        self._eod_attempted = False
        self._eod_bars: dict[str, DailyClose] = {}

    @property
    def mode(self) -> DataMode:
        return self._mode

    async def start(self, tickers: list[str]) -> None:
        # retries=0: the poll loop is the retry, and each urllib3 retry of a 429
        # would spend another request from a 5-per-minute allowance.
        self._client = RESTClient(api_key=self._api_key, retries=0)
        self._tickers = [normalize_ticker(t) for t in tickers]

        # Immediate first poll so the cache has data right away. In eod mode this
        # only discovers the plan limit; the loop fetches closes without blocking.
        await self._poll_once()

        self._task = asyncio.create_task(self._poll_loop(), name="massive-poller")
        logger.info(
            "Massive poller started: %d tickers, mode=%s", len(self._tickers), self._mode
        )

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        self._client = None
        logger.info("Massive poller stopped")

    async def add_ticker(self, ticker: str) -> None:
        ticker = normalize_ticker(ticker)
        if ticker not in self._tickers:
            self._tickers.append(ticker)
            self._publish_eod([ticker])  # Live mode: appears on the next poll

    async def remove_ticker(self, ticker: str) -> None:
        ticker = normalize_ticker(ticker)
        self._tickers = [t for t in self._tickers if t != ticker]
        self._cache.remove(ticker)

    def get_tickers(self) -> list[str]:
        return list(self._tickers)

    # --- Internal ---

    def _next_delay(self) -> float:
        if self._mode == "live":
            return self._interval
        return EOD_REFRESH_SECONDS if self._eod_attempted else 0.0

    async def _poll_loop(self) -> None:
        while True:
            await asyncio.sleep(self._next_delay())
            await self._poll_once()

    async def _poll_once(self) -> None:
        if not self._tickers or not self._client:
            return
        try:
            if self._mode == "live":
                await self._poll_live()
            else:
                self._eod_attempted = True
                await self._poll_eod()
        except BadResponse as e:
            if self._mode == "live" and _is_plan_limit(e):
                self._mode = "eod"
                logger.warning(
                    "Massive plan has no snapshot access: showing end-of-day closes, "
                    "not live prices. Remove MASSIVE_API_KEY to use the simulator."
                )
            else:
                logger.error("Massive poll failed: %s", e)
        except Exception as e:  # Network errors, rate limits: retry next cycle
            logger.error("Massive poll failed: %s", e)

    async def _poll_live(self) -> None:
        tickers = list(self._tickers)
        snapshots = await asyncio.to_thread(self._fetch_snapshots, tickers)
        for snap in snapshots:
            price = snapshot_price(snap)
            # Ignore tickers removed while this request was in flight
            if price is None or snap.ticker not in self._tickers:
                continue
            self._cache.update(
                ticker=snap.ticker,
                price=price,
                timestamp=snapshot_timestamp(snap),
                previous_close=snapshot_previous_close(snap),
            )

    def _fetch_snapshots(self, tickers: list[str]) -> list[TickerSnapshot]:
        """Synchronous REST call. Runs in a thread. market_type must be a string."""
        return self._client.get_snapshot_all("stocks", tickers)

    async def _poll_eod(self) -> None:
        sessions = await _latest_sessions(self._client, self._eod_call_spacing)
        if not sessions:
            logger.error("Massive: no daily bars in the last %d days", EOD_LOOKBACK_DAYS)
            return
        self._eod_bars = _closes_by_ticker(sessions)
        self._publish_eod(self._tickers)

    def _publish_eod(self, tickers: list[str]) -> None:
        for ticker in tickers:
            if ticker in self._eod_bars:
                close, previous_close, timestamp = self._eod_bars[ticker]
                self._cache.update(ticker, close, timestamp, previous_close)
