"""Tests for market data source factory."""

import os
from unittest.mock import patch

from app.market.cache import PriceCache
from app.market.factory import (
    create_history_provider,
    create_history_service,
    create_market_data_source,
)
from app.market.history import MassiveHistory, SyntheticHistory
from app.market.massive_client import MassiveDataSource
from app.market.simulator import SimulatorDataSource


class TestFactory:
    """Tests for create_market_data_source factory."""

    def test_creates_simulator_when_no_api_key(self):
        """Test that simulator is created when MASSIVE_API_KEY is not set."""
        cache = PriceCache()

        with patch.dict(os.environ, {}, clear=True):
            source = create_market_data_source(cache)

        assert isinstance(source, SimulatorDataSource)

    def test_creates_simulator_when_api_key_empty(self):
        """Test that simulator is created when MASSIVE_API_KEY is empty."""
        cache = PriceCache()

        with patch.dict(os.environ, {"MASSIVE_API_KEY": ""}, clear=True):
            source = create_market_data_source(cache)

        assert isinstance(source, SimulatorDataSource)

    def test_creates_simulator_when_api_key_whitespace(self):
        """Test that simulator is created when MASSIVE_API_KEY is whitespace."""
        cache = PriceCache()

        with patch.dict(os.environ, {"MASSIVE_API_KEY": "   "}, clear=True):
            source = create_market_data_source(cache)

        assert isinstance(source, SimulatorDataSource)

    def test_creates_massive_when_api_key_set(self):
        """Test that Massive client is created when MASSIVE_API_KEY is set."""
        cache = PriceCache()

        with patch.dict(os.environ, {"MASSIVE_API_KEY": "test-key"}, clear=True):
            source = create_market_data_source(cache)

        assert isinstance(source, MassiveDataSource)

    def test_massive_receives_api_key(self):
        """Test that Massive client receives the API key."""
        cache = PriceCache()

        with patch.dict(os.environ, {"MASSIVE_API_KEY": "test-key-123"}, clear=True):
            source = create_market_data_source(cache)

        assert isinstance(source, MassiveDataSource)
        assert source._api_key == "test-key-123"

    def test_simulator_receives_cache(self):
        """Test that simulator receives the cache reference."""
        cache = PriceCache()

        with patch.dict(os.environ, {}, clear=True):
            source = create_market_data_source(cache)

        assert isinstance(source, SimulatorDataSource)
        assert source._cache is cache

    def test_massive_receives_cache(self):
        """Test that Massive client receives the cache reference."""
        cache = PriceCache()

        with patch.dict(os.environ, {"MASSIVE_API_KEY": "test-key"}, clear=True):
            source = create_market_data_source(cache)

        assert isinstance(source, MassiveDataSource)
        assert source._cache is cache


class TestHistoryFactory:
    def test_synthetic_without_massive(self, monkeypatch):
        monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
        assert isinstance(create_history_provider(), SyntheticHistory)

    def test_massive_with_a_key(self, monkeypatch):
        monkeypatch.setenv("MASSIVE_API_KEY", "test-key")
        monkeypatch.delenv("MASSIVE_SEED_SIMULATOR", raising=False)
        assert isinstance(create_history_provider(), MassiveHistory)

    def test_seeded_simulator_gets_synthetic_history(self, monkeypatch):
        monkeypatch.setenv("MASSIVE_API_KEY", "test-key")
        monkeypatch.setenv("MASSIVE_SEED_SIMULATOR", "true")
        assert isinstance(create_history_provider(), SyntheticHistory)

    def test_day_settings(self, monkeypatch, tmp_path):
        monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
        monkeypatch.setenv("HISTORY_BACKFILL_DAYS", "0")
        monkeypatch.setenv("HISTORY_RETENTION_DAYS", "1")  # Below the minimum: default
        history = create_history_service(tmp_path / "x.db", PriceCache())
        assert history._backfill_days == 0
        assert history.retention_days == 30
