"""Factory for creating market data sources."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from .cache import PriceCache
from .history import HistoryProvider, MassiveHistory, SyntheticHistory
from .interface import MarketDataSource
from .massive_client import DailyCloses, MassiveDataSource
from .recorder import DEFAULT_BACKFILL_DAYS, DEFAULT_RETENTION_DAYS, HistoryService
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


def _days(name: str, default: float, minimum: float) -> float:
    """A day count from the environment, or the default if unset or invalid."""
    raw = os.environ.get(name, "").strip()
    try:
        value = float(raw)
    except ValueError:
        if raw:
            logger.warning("Ignoring invalid %s: %r", name, raw)
        return default
    if value < minimum:
        logger.warning("Ignoring %s below %s: %r", name, minimum, raw)
        return default
    return value


def _uses_massive_prices() -> tuple[str, bool]:
    api_key = os.environ.get("MASSIVE_API_KEY", "").strip()
    seed_simulator = os.environ.get("MASSIVE_SEED_SIMULATOR", "").strip().lower() == "true"
    return api_key, bool(api_key) and not seed_simulator


def create_history_provider() -> HistoryProvider:
    """Real history when prices are real Massive prices, otherwise synthetic.

    A simulator seeded from real closes still produces simulated prices, so its
    history is synthetic too.
    """
    api_key, massive = _uses_massive_prices()
    if massive:
        logger.info("History: Massive aggregates")
        return MassiveHistory(api_key)
    logger.info("History: synthetic, from the simulator's model")
    return SyntheticHistory()


def create_history_service(db_path: Path, price_cache: PriceCache) -> HistoryService:
    """HISTORY_BACKFILL_DAYS (0 turns backfill off) and HISTORY_RETENTION_DAYS apply."""
    return HistoryService(
        db_path,
        price_cache,
        create_history_provider(),
        backfill_days=_days("HISTORY_BACKFILL_DAYS", DEFAULT_BACKFILL_DAYS, minimum=0),
        retention_days=_days("HISTORY_RETENTION_DAYS", DEFAULT_RETENTION_DAYS, minimum=2),
    )


def create_market_data_source(price_cache: PriceCache) -> MarketDataSource:
    """Create the appropriate market data source based on environment variables.

    - MASSIVE_API_KEY set and MASSIVE_SEED_SIMULATOR=true → SimulatorDataSource
      starting from real closes
    - MASSIVE_API_KEY set → MassiveDataSource (real market data)
    - Otherwise → SimulatorDataSource (GBM simulation)

    Returns an unstarted source. Caller must await source.start(tickers).
    """
    api_key = os.environ.get("MASSIVE_API_KEY", "").strip()

    seed_simulator = os.environ.get("MASSIVE_SEED_SIMULATOR", "").strip().lower() == "true"

    if api_key and seed_simulator:
        logger.info("Market data source: GBM Simulator from real Massive closes")
        return SimulatorDataSource(price_cache=price_cache, closes=DailyCloses(api_key))
    elif api_key:
        logger.info("Market data source: Massive API (real data)")
        return MassiveDataSource(
            api_key=api_key,
            price_cache=price_cache,
            poll_interval=_poll_interval(),
        )
    else:
        logger.info("Market data source: GBM Simulator")
        return SimulatorDataSource(price_cache=price_cache)
