"""Market data subsystem for FinAlly.

Public API:
    PriceUpdate         - Immutable price snapshot dataclass
    PriceCache          - Thread-safe in-memory price store
    MarketDataSource    - Abstract interface for data providers
    DataMode            - Kind of prices a source produces: simulated, live or eod
    normalize_ticker    - Canonical ticker form, for use at API boundaries
    create_market_data_source - Factory that selects simulator or Massive
    create_stream_router - FastAPI router factory for SSE endpoint
    create_history_service - Records live prices as bars and backfills history
"""

from .cache import PriceCache
from .factory import create_history_service, create_market_data_source
from .interface import DataMode, MarketDataSource, normalize_ticker
from .models import PriceUpdate
from .stream import create_stream_router

__all__ = [
    "PriceUpdate",
    "PriceCache",
    "MarketDataSource",
    "DataMode",
    "normalize_ticker",
    "create_market_data_source",
    "create_stream_router",
    "create_history_service",
]
