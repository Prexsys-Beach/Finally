"""Settings storage and the synthetic-history cutoff."""

import json
from contextlib import closing

import pytest

from app.db import connect, init_db
from app.settings import SettingsError, get_settings, synthetic_cutoff_days, update_settings


@pytest.fixture
def conn(tmp_path):
    path = tmp_path / "settings.db"
    init_db(path)
    with closing(connect(path)) as connection:
        yield connection


@pytest.mark.parametrize(
    ("value", "days"),
    [("never", None), ("day", 1), ("week", 7), ("month", 30), ("quarter", 91), ("year", 365)],
)
def test_cutoff_days(conn, value, days):
    update_settings(conn, {"synthetic_history_cutoff": value})
    assert synthetic_cutoff_days(conn) == days


def test_default_cutoff_is_a_month(conn):
    assert synthetic_cutoff_days(conn) == 30


def test_stored_value_no_longer_allowed_falls_back(conn):
    conn.execute(
        "INSERT INTO user_settings (user_id, key, value, updated_at) VALUES (?, ?, ?, ?)",
        ("default", "synthetic_history_cutoff", json.dumps("decade"), "now"),
    )
    assert get_settings(conn)["synthetic_history_cutoff"] == "month"


def test_rejects_unknown_keys(conn):
    with pytest.raises(SettingsError, match="Unknown setting"):
        update_settings(conn, {"theme": "dark"})


def test_auto_switch_is_a_true_boolean(conn):
    assert get_settings(conn)["analysis_panel_auto_switch"] is True
    assert (
        update_settings(conn, {"analysis_panel_auto_switch": False})["analysis_panel_auto_switch"]
        is False
    )
    for value in (0, 1, "false", None):
        with pytest.raises(
            SettingsError, match="analysis_panel_auto_switch must be one of: true, false"
        ):
            update_settings(conn, {"analysis_panel_auto_switch": value})


def test_cutoff_rejects_lookalikes(conn):
    with pytest.raises(SettingsError):
        update_settings(conn, {"synthetic_history_cutoff": True})
