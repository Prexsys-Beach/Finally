# Market Data Interface

The unified Python API for stock prices in FinAlly. It uses Massive when `MASSIVE_API_KEY` is set and the simulator otherwise, and the rest of the app can't tell which is running.

**Status:** built in `backend/app/market/`, including the changes listed under "Required Changes". Those changes are kept below as a record of what was fixed and why.

**Evidence:** all 92 backend tests pass on `massive` 2.2.0 and 2.9.1, including `tests/market/test_massive_real_models.py`, which runs the real client with only the HTTP transport faked, and `ruff` passes. `eod` mode was also run live with a real key on 2026-11-06, using `MassiveDataSource` with only the transport routed through a proxy. **`live` mode hasn't been run against real snapshots yet**, because that key has no snapshot access.

Related docs: `MASSIVE_API.md` (API facts) and `MARKET_SIMULATOR.md` (the simulator).

## The Design

Data sources push prices into a shared cache, and everything else reads from the cache. Nothing downstream asks a source for a price.

```
create_market_data_source(cache)
        │  MASSIVE_API_KEY set?
        ├── yes ──▶ MassiveDataSource     (REST poller, 15 s default)
        └── no ───▶ SimulatorDataSource   (GBM, 500 ms)
                          │
                          │  cache.update(...)
                          ▼
                     PriceCache  ◀─── single source of truth
                          │
        ┌─────────────────┼──────────────────┐
        ▼                 ▼                  ▼
  SSE /api/stream/   Portfolio          Trade execution
  prices             valuation          and chat context
```

This means:

- A slow or failing upstream can't stall a request, because readers only touch memory.
- Massive's 15-second data and the simulator's 500 ms data use the same SSE path.
- Adding another provider means writing one class.

## Using It

Only these names are public, all from `app.market`:

```python
from app.market import PriceCache, PriceUpdate, MarketDataSource, DataMode
from app.market import create_market_data_source, create_stream_router, normalize_ticker
```

```python
# Startup
cache = PriceCache()
source = create_market_data_source(cache)     # Unstarted
await source.start(tickers)

# Reads, from anywhere
price = cache.get_price("AAPL")               # float | None
update = cache.get("AAPL")                    # PriceUpdate | None
prices = cache.get_all()                      # dict[str, PriceUpdate]

# Watchlist changes
await source.add_ticker("PYPL")
await source.remove_ticker("NFLX")

# Shutdown
await source.stop()
```

FastAPI wiring, using the app lifespan:

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI

@asynccontextmanager
async def lifespan(app: FastAPI):
    cache = PriceCache()
    source = create_market_data_source(cache)
    await source.start(tracked_tickers())     # See "Integration Rules"
    app.state.price_cache = cache
    app.state.market_source = source
    app.include_router(create_stream_router(cache))
    yield
    await source.stop()
```

## Contract

### `MarketDataSource`

| Member | Behaviour |
|---|---|
| `await start(tickers)` | Publishes a first set of prices where possible, then starts the background task. Call once |
| `await stop()` | Cancels the task. Safe to call repeatedly |
| `await add_ticker(ticker)` | Normalises the ticker. No-op if already tracked |
| `await remove_ticker(ticker)` | Stops tracking and removes it from the cache. No-op if unknown |
| `get_tickers()` | Returns a copy of the tracked list |
| `mode` *(new)* | `"simulated"`, `"live"` or `"eod"` |

A source never raises from its background task. Failures are logged and retried next cycle, so a provider outage leaves the last good prices in the cache.

### `PriceCache`

| Member | Behaviour |
|---|---|
| `update(ticker, price, timestamp=None, previous_close=None)` *(`previous_close` is new)* | Writes a `PriceUpdate`, rounding to 2 dp. `previous_price` comes from the last entry. A `None` `previous_close` keeps the existing value |
| `get(ticker)`, `get_price(ticker)` | Latest value or `None` |
| `get_all()` | Shallow copy of all entries |
| `remove(ticker)` | Deletes an entry |
| `version` | Increments on each update. SSE uses it to skip unchanged data |

Writes come from the event loop today, and the cache is locked so writing from a worker thread stays safe.

### `PriceUpdate`

An immutable snapshot of one ticker. Each field or property below appears in `to_dict()`, which is the SSE payload.

| Field | Meaning |
|---|---|
| `ticker`, `price`, `timestamp` | Symbol, latest price, Unix seconds |
| `previous_price` | Price at the last update. Drives the green/red flash |
| `change`, `change_percent`, `direction` | Tick-to-tick move |
| `previous_close` *(new)* | Reference price for the day, or `None` |
| `day_change_percent` *(new)* | Percent move from `previous_close`, or `None`. Drives the watchlist's "daily change %" |

### `create_market_data_source(cache)`

| Environment | Result |
|---|---|
| `MASSIVE_API_KEY` empty or missing | `SimulatorDataSource` |
| `MASSIVE_API_KEY` set | `MassiveDataSource` |
| `MASSIVE_POLL_INTERVAL` *(new)* | Poll seconds, default `15`. Invalid or non-positive values use the default |

## Source Modes

`mode` is what the app actually gets, which depends on the key's plan as well as whether a key exists.

| Key | `mode` | Prices | Update rate | `previous_close` |
|---|---|---|---|---|
| None | `simulated` | GBM simulation | 500 ms | Starting price this run |
| Advanced, Business | `live` | Real-time | Poll interval | `prev_day.close` |
| Starter, Developer | `live` | 15 minutes delayed | Poll interval | `prev_day.close` |
| Basic (free) | `eod` | Latest daily close | Hourly refresh | Close of the session before |
| Invalid | `live` | None; errors logged each poll | Retries each poll | n/a |

The API can't reveal the delay directly, so `live` covers both real-time and delayed data. The UI should therefore say "market data", not "real-time".

`eod` is detected at runtime: the first snapshot poll gets a 403 `NOT_AUTHORIZED`, and the source switches over and logs a warning. In the live run, `start()` returned in 0.2 s and prices appeared after 26 s, because the walk-back is spaced to respect the rate limit. Until then `get_price()` returns `None`.

## Integration Rules

The next backend work has to follow these rules.

1. **Track the union of watchlist and positions.** `cache.remove()` drops the price, so removing a held ticker from the watchlist would leave its position unpriced. At startup pass watchlist ∪ open positions. On watchlist removal, only call `source.remove_ticker()` if there's no open position. Before a trade in an untracked ticker, call `source.add_ticker()`.
2. **Reject trades with no price.** `get_price()` returns `None` for tickers that are new or unknown to Massive. In live mode, a new ticker has no price until the next poll, so the API should return a clear error rather than filling at a guess.
3. **Treat a missing price as normal.** The watchlist should show a placeholder. A ticker Massive doesn't recognise is expected to stay that way, though this needs confirming with a real key.
4. **Expose `mode` in `/api/health`.** A Basic key gives prices that don't move, which looks like a bug without this. The header can show it too.
5. **Normalise tickers at the API boundary too,** with `normalize_ticker()`, so the database and sources agree. Massive tickers are case-sensitive.

## Required Changes

### Must fix: the Massive path doesn't work

With a real key today, the cache stays empty and every price is missing. Both defects were reproduced by running `MassiveDataSource` against the real client.

| # | Defect | Effect | Fix |
|---|---|---|---|
| 1 | `_fetch_snapshots` passes `SnapshotMarketType.STOCKS`. The client's `get_locale()` compares with the string `"stocks"` and interpolates the raw Enum | Requests `/v2/snapshot/locale/global/markets/SnapshotMarketType.STOCKS/tickers`. **The live API returns 404** | Pass `"stocks"` |
| 2 | `_poll_once` reads `snap.last_trade.timestamp`, which doesn't exist | With #1 fixed, every ticker is skipped with an `AttributeError` warning | Use `sip_timestamp / 1e9` |
| 3 | The `/ 1000` conversion assumes milliseconds | Trade timestamps are nanoseconds, so times would be wrong by a factor of a million | Same fix |
| 4 | Basic keys have no snapshot access (documented) | Basic users get 403s forever and no prices | Fall back to `eod` |
| 5 | `test_massive.py` builds snapshots with `MagicMock` | Mocks invent `.timestamp`, so all tests pass with the bugs present | Build from `TickerSnapshot.from_dict()` |


### Should fix: gaps against the spec

| # | Gap | Fix |
|---|---|---|
| 6 | `PLAN.md` requires "daily change %", but `change_percent` is tick-to-tick | Add `previous_close` and `day_change_percent` |
| 7 | The poll interval can't be configured, so paid plans are stuck at 15 s | Add `MASSIVE_POLL_INTERVAL` |
| 8 | `lastTrade` depends on the plan | Use the fallback chain |
| 9 | A ticker removed mid-poll is written back to the cache and stays there | Ignore snapshots for untracked tickers |
| 10 | The simulator doesn't normalise: `add_ticker("aapl")` creates a second instrument at a random price | Shared `normalize_ticker()` |
| 11 | A 429 costs 4 requests | `RESTClient(retries=0)` |

### `models.py`

Add one field and one property, and include both in `to_dict()`.

```python
@dataclass(frozen=True, slots=True)
class PriceUpdate:
    ticker: str
    price: float
    previous_price: float
    timestamp: float = field(default_factory=time.time)  # Unix seconds
    previous_close: float | None = None  # Reference for daily change; None if unknown

    @property
    def day_change_percent(self) -> float | None:
        """Percentage change from previous_close, or None if it is unknown."""
        if not self.previous_close:
            return None
        return round((self.price - self.previous_close) / self.previous_close * 100, 4)
```

```python
    # In to_dict()
    "previous_close": self.previous_close,
    "day_change_percent": self.day_change_percent,
```

### `cache.py`

```python
    def update(
        self,
        ticker: str,
        price: float,
        timestamp: float | None = None,
        previous_close: float | None = None,
    ) -> PriceUpdate:
        with self._lock:
            ts = timestamp or time.time()
            prev = self._prices.get(ticker)
            previous_price = prev.price if prev else price
            if previous_close is None and prev:
                previous_close = prev.previous_close  # Sticky across ticks

            update = PriceUpdate(
                ticker=ticker,
                price=round(price, 2),
                previous_price=round(previous_price, 2),
                timestamp=ts,
                previous_close=round(previous_close, 2) if previous_close else None,
            )
            self._prices[ticker] = update
            self._version += 1
            return update
```

### `interface.py`

```python
from typing import Literal

DataMode = Literal["simulated", "live", "eod"]


def normalize_ticker(ticker: str) -> str:
    """Canonical ticker form. Massive tickers are case-sensitive and uppercase."""
    return ticker.upper().strip()
```

And on `MarketDataSource`:

```python
    @property
    @abstractmethod
    def mode(self) -> DataMode:
        """What kind of prices this source is currently producing."""
```

### `factory.py`

```python
"""Factory for creating market data sources."""

from __future__ import annotations

import logging
import os

from .cache import PriceCache
from .interface import MarketDataSource
from .massive_client import MassiveDataSource
from .simulator import SimulatorDataSource

logger = logging.getLogger(__name__)

DEFAULT_POLL_INTERVAL = 15.0  # Seconds; safe on any plan with snapshot access


def _poll_interval() -> float:
    """MASSIVE_POLL_INTERVAL in seconds, or the default if unset or invalid."""
    raw = os.environ.get("MASSIVE_POLL_INTERVAL", "").strip()
    try:
        return float(raw) if float(raw) > 0 else DEFAULT_POLL_INTERVAL
    except ValueError:
        if raw:
            logger.warning("Ignoring invalid MASSIVE_POLL_INTERVAL: %r", raw)
        return DEFAULT_POLL_INTERVAL


def create_market_data_source(price_cache: PriceCache) -> MarketDataSource:
    """Create the appropriate market data source based on environment variables.

    - MASSIVE_API_KEY set and non-empty → MassiveDataSource (real market data)
    - Otherwise → SimulatorDataSource (GBM simulation)

    Returns an unstarted source. Caller must await source.start(tickers).
    """
    api_key = os.environ.get("MASSIVE_API_KEY", "").strip()

    if api_key:
        logger.info("Market data source: Massive API (real data)")
        return MassiveDataSource(
            api_key=api_key,
            price_cache=price_cache,
            poll_interval=_poll_interval(),
        )
    else:
        logger.info("Market data source: GBM Simulator")
        return SimulatorDataSource(price_cache=price_cache)
```

### `massive_client.py`

Replaces the whole file.

```python
"""Massive (formerly Polygon.io) API client for real market data."""

from __future__ import annotations

import asyncio
import logging
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
        self._eod_bars: dict[str, tuple[float, float | None, float]] = {}

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
        sessions = await self._latest_sessions()
        if not sessions:
            logger.error("Massive: no daily bars in the last %d days", EOD_LOOKBACK_DAYS)
            return
        previous = {b.ticker: b.close for b in sessions[1]} if len(sessions) > 1 else {}
        self._eod_bars = {
            bar.ticker: (bar.close, previous.get(bar.ticker), bar.timestamp / 1e3)
            for bar in sessions[0]
            if _positive(bar.close) and bar.timestamp
        }
        self._publish_eod(self._tickers)

    def _publish_eod(self, tickers: list[str]) -> None:
        for ticker in tickers:
            if ticker in self._eod_bars:
                close, previous_close, timestamp = self._eod_bars[ticker]
                self._cache.update(ticker, close, timestamp, previous_close)

    async def _latest_sessions(self) -> list[list[GroupedDailyAgg]]:
        """Walk back from today to the two most recent sessions with data."""
        sessions: list[list[GroupedDailyAgg]] = []
        today = datetime.now(UTC).date()
        for offset in range(EOD_LOOKBACK_DAYS):
            day = today - timedelta(days=offset)
            if day.weekday() >= 5:
                continue
            bars = await self._fetch_grouped_day(day)
            if bars:
                sessions.append(bars)
            if len(sessions) == 2:
                break
            await asyncio.sleep(self._eod_call_spacing)
        return sessions

    async def _fetch_grouped_day(self, day: date) -> list[GroupedDailyAgg]:
        """Bars for one date; empty if it is a holiday or too recent for the plan."""
        try:
            return await asyncio.to_thread(
                self._client.get_grouped_daily_aggs, day.isoformat(), adjusted=True
            )
        except BadResponse as e:
            if _is_plan_limit(e):
                return []
            raise
```

### `simulator.py`

See "Required Changes" in `MARKET_SIMULATOR.md`.

### Tests

Replace the `MagicMock` helper in `test_massive.py`:

```python
from massive.rest.models import TickerSnapshot


def _make_snapshot(ticker: str, price: float, timestamp_ms: int) -> TickerSnapshot:
    """Build a real snapshot from a documented payload. Never use MagicMock here:
    it invents attributes, which is how a nonexistent field went unnoticed."""
    return TickerSnapshot.from_dict(
        {"ticker": ticker, "lastTrade": {"p": price, "t": timestamp_ms * 1_000_000}}
    )
```

Add tests that use the real client with `client.client.request` replaced by a fake, so URL building and parsing are both exercised:

- The request URL is exactly `/v2/snapshot/locale/us/markets/stocks/tickers`.
- Price falls back through trade, minute, day and previous close, treating `0` as missing.
- Nanosecond and millisecond timestamps convert correctly.
- A 403 switches to `eod`; 401 and 404 don't.
- `eod` skips weekends, handles a 403 on the newest date, and uses the two latest sessions.
- `add_ticker` in `eod` mode makes no API call.
- A ticker removed mid-poll stays removed.
- An `eod` fetch that finds nothing doesn't spin.

### Before Relying on It

The 403 fallback and end-of-day path are confirmed live. With a key that has snapshot access, run this smoke test to confirm the rest: whether `lastTrade` appears on that plan, the real timestamp units, and how unknown tickers are handled.

```bash
cd backend
MASSIVE_API_KEY=your_key uv run python -c "
from massive import RESTClient
for s in RESTClient().get_snapshot_all('stocks', ['AAPL', 'MSFT']):
    print(s.ticker, s.last_trade, s.prev_day, s.updated)"
```

## Open Decisions

1. **What should a Basic key do?** Decided on 2026-11-06: keep the `eod` behaviour. To get ticking prices on a demo, leave `MASSIVE_API_KEY` unset so the simulator runs. The UI should still show a visible mode label.
2. **Should an invalid key fall back to the simulator?** Today it logs errors and shows no prices. Recommendation: leave it, because a loud failure is easier to diagnose than quietly showing fake prices.
