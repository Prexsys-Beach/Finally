"""Settings endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from .. import settings
from .deps import Db

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _body(values: dict) -> dict:
    return {"settings": values, "choices": settings.setting_choices()}


@router.get("")
async def get_settings(db: Db) -> dict:
    return _body(settings.get_settings(db))


@router.put("")
async def update_settings(changes: dict[str, Any], db: Db) -> dict:
    try:
        return _body(settings.update_settings(db, changes))
    except settings.SettingsError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
