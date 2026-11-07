"""FinAlly FastAPI application."""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, closing
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .db import connect, database_path, init_db
from .market import PriceCache, create_market_data_source, create_stream_router
from .portfolio import snapshot_loop
from .routes import chat, portfolio, system, watchlist
from .watchlist import tracked_tickers

logging.basicConfig(level=logging.INFO)

_DEFAULT_STATIC_DIR = Path(__file__).resolve().parents[1] / "static"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    db_path = app.state.db_path
    cache = app.state.price_cache

    init_db(db_path)
    with closing(connect(db_path)) as conn:
        tickers = tracked_tickers(conn)

    source = create_market_data_source(cache)
    await source.start(tickers)
    app.state.market_source = source
    snapshots = asyncio.create_task(snapshot_loop(db_path, cache), name="portfolio-snapshots")

    yield

    snapshots.cancel()
    await source.stop()


def create_app() -> FastAPI:
    app = FastAPI(title="FinAlly", lifespan=lifespan)
    app.state.db_path = database_path()
    app.state.price_cache = PriceCache()

    app.include_router(create_stream_router(app.state.price_cache))
    app.include_router(portfolio.router)
    app.include_router(watchlist.router)
    app.include_router(chat.router)
    app.include_router(system.router)

    # Must come last: "/" would otherwise catch the API routes
    static_dir = Path(os.environ.get("FINALLY_STATIC_DIR", _DEFAULT_STATIC_DIR))
    if static_dir.is_dir():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="frontend")

    return app


app = create_app()
