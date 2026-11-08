"""Prediction journal endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from .. import predictions
from .deps import Db

router = APIRouter(prefix="/api/predictions", tags=["predictions"])


@router.get("")
async def recent(db: Db, limit: Annotated[int, Query(ge=1, le=500)] = 50) -> dict:
    """The latest assistant predictions, newest first, with their baselines' outcomes."""
    return {"predictions": predictions.recent(db, limit)}


@router.get("/stats")
async def stats(db: Db) -> dict:
    """Hit rate, Brier score and calibration per data mode, assistant vs coin flip."""
    return predictions.stats(db)
