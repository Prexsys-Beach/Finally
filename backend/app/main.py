"""FinAlly FastAPI application."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, closing
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .db import connect, database_path, init_db
from .market import (
    PriceCache,
    create_history_service,
    create_market_data_source,
    create_stream_router,
)
from .portfolio import snapshot_loop
from .routes import analytics, chat, market, portfolio, settings, system, watchlist
from .watchlist import tracked_tickers

logging.basicConfig(level=logging.INFO)

_DEFAULT_STATIC_DIR = Path(__file__).resolve().parents[1] / "static"


def stop_on_shutdown_signal(stop: threading.Event) -> None:
    """Set stop on SIGINT or SIGTERM, then let the server handle the signal as usual.

    Uvicorn waits for open connections to close before running shutdown code, and
    an SSE stream only ends when its client leaves. Without this, one open browser
    tab blocks shutdown forever, so the lifespan's own shutdown is too late.
    """
    if threading.current_thread() is not threading.main_thread():
        return  # Signal handlers can only be set here; test clients run elsewhere

    for signum in (signal.SIGINT, signal.SIGTERM):
        previous = signal.getsignal(signum)

        def handler(number, frame, previous=previous):
            stop.set()
            if callable(previous):
                previous(number, frame)

        signal.signal(signum, handler)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    db_path = app.state.db_path
    cache = app.state.price_cache
    stop_on_shutdown_signal(app.state.shutting_down)

    init_db(db_path)
    with closing(connect(db_path)) as conn:
        tickers = tracked_tickers(conn)

    source = create_market_data_source(cache)
    await source.start(tickers)
    app.state.market_source = source
    history = create_history_service(db_path, cache)
    await history.start()
    app.state.history = history
    snapshots = asyncio.create_task(snapshot_loop(db_path, cache), name="portfolio-snapshots")

    yield

    snapshots.cancel()
    await history.stop()
    await source.stop()


def create_app() -> FastAPI:
    app = FastAPI(title="FinAlly", lifespan=lifespan)
    app.state.db_path = database_path()
    app.state.price_cache = PriceCache()
    app.state.shutting_down = threading.Event()

    app.include_router(create_stream_router(app.state.price_cache, app.state.shutting_down))
    app.include_router(portfolio.router)
    app.include_router(watchlist.router)
    app.include_router(chat.router)
    app.include_router(market.router)
    app.include_router(analytics.router)
    app.include_router(settings.router)
    app.include_router(system.router)

    # Must come last: "/" would otherwise catch the API routes
    static_dir = Path(os.environ.get("FINALLY_STATIC_DIR", _DEFAULT_STATIC_DIR))
    if static_dir.is_dir():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="frontend")

    return app


app = create_app()
