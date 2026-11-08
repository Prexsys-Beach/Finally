"""User settings: stored per user, validated here, with defaults for unset keys."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from .db import DEFAULT_USER_ID, transaction, utc_now

# How much real history a ticker needs before synthetic bars stop being used in
# analysis. None: synthetic bars are always used.
SYNTHETIC_CUTOFF_DAYS: dict[str, float | None] = {
    "never": None,
    "day": 1,
    "week": 7,
    "month": 30,
    "quarter": 91,
    "year": 365,
}


@dataclass(frozen=True)
class Setting:
    default: object
    choices: tuple


SETTINGS: dict[str, Setting] = {
    "synthetic_history_cutoff": Setting("month", tuple(SYNTHETIC_CUTOFF_DAYS)),
    # Bring the matching analysis view forward when an assistant reply uses it
    "analysis_panel_auto_switch": Setting(True, (True, False)),
}


def _allowed(setting: Setting, value: object) -> bool:
    """In the choices and of the default's type: JSON 1 is not true, and 0 is not false."""
    return type(value) is type(setting.default) and value in setting.choices


class SettingsError(ValueError):
    """An unknown key or a value the setting doesn't allow."""


def get_settings(conn: sqlite3.Connection) -> dict:
    """Every setting, stored value or default. Stored values no longer allowed fall back."""
    rows = conn.execute(
        "SELECT key, value FROM user_settings WHERE user_id = ?", (DEFAULT_USER_ID,)
    ).fetchall()
    stored = {row["key"]: json.loads(row["value"]) for row in rows}
    return {
        key: stored[key] if key in stored and _allowed(setting, stored[key]) else setting.default
        for key, setting in SETTINGS.items()
    }


def setting_choices() -> dict[str, list]:
    return {key: list(setting.choices) for key, setting in SETTINGS.items()}


def update_settings(conn: sqlite3.Connection, changes: dict) -> dict:
    """Save the changes, all or none. Returns every setting afterwards."""
    for key, value in changes.items():
        setting = SETTINGS.get(key)
        if setting is None:
            raise SettingsError(f"Unknown setting: {key}")
        if not _allowed(setting, value):
            allowed = ", ".join(json.dumps(choice) for choice in setting.choices)
            raise SettingsError(f"{key} must be one of: {allowed}")
    now = utc_now()
    with transaction(conn):
        conn.executemany(
            """
            INSERT INTO user_settings (user_id, key, value, updated_at) VALUES (?, ?, ?, ?)
            ON CONFLICT (user_id, key) DO UPDATE SET
                value = excluded.value, updated_at = excluded.updated_at
            """,
            [(DEFAULT_USER_ID, key, json.dumps(value), now) for key, value in changes.items()],
        )
    return get_settings(conn)


def synthetic_cutoff_days(conn: sqlite3.Connection) -> float | None:
    return SYNTHETIC_CUTOFF_DAYS[get_settings(conn)["synthetic_history_cutoff"]]
