"""Factory for creating market data sources."""

from __future__ import annotations

import logging
import os

from .cache import PriceCache
from .interface import MarketDataSource
from .massive_client import DailyCloses, MassiveDataSource
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
