"""Unit tests for src/exchange_rates.py."""

from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
import requests

from app import app as flask_app
from models import ExchangeRateCache, db
from src.exchange_rates import (
    CACHE_TTL_SECONDS,
    RateBundle,
    cache_key_for,
    cross_rates_via_usd,
    fetch_latest_rates,
    get_rates_for,
    is_rate_fresh,
)


@pytest.fixture
def app():
    """Fresh in-memory DB schema for cache-layer tests."""
    flask_app.config["TESTING"] = True
    with flask_app.app_context():
        db.drop_all()
        db.create_all()
        yield flask_app
        db.session.remove()
        db.drop_all()


# ───────────────────────────  is_rate_fresh  ──────────────────────────


def test_is_rate_fresh_just_fetched():
    now = datetime(2026, 6, 9, 12, 0, 0)
    assert is_rate_fresh(now, now) is True


def test_is_rate_fresh_within_window():
    now = datetime(2026, 6, 9, 12, 0, 0)
    fetched = now - timedelta(hours=23)
    assert is_rate_fresh(fetched, now) is True


def test_is_rate_fresh_past_ttl():
    now = datetime(2026, 6, 9, 12, 0, 0)
    fetched = now - timedelta(seconds=CACHE_TTL_SECONDS + 60)
    assert is_rate_fresh(fetched, now) is False


# ───────────────────────────  cache_key_for  ──────────────────────────


def test_cache_key_for_uppercases_codes():
    key = cache_key_for("usd", "eur", date(2026, 6, 9))
    assert key == ("USD", "EUR", date(2026, 6, 9))


def test_cache_key_for_passes_date_through():
    d = date(2025, 1, 1)
    base, target, returned = cache_key_for("USD", "GBP", d)
    assert returned == d
    assert (base, target) == ("USD", "GBP")


# ──────────────────────────  cross_rates_via_usd  ─────────────────────


def test_cross_rates_target_usd_inverts_per_usd_rates():
    # target=USD means "USD per source". If 1 USD = 1.10 EUR (the input
    # convention), then 1 EUR = 1/1.10 USD ≈ 0.909.
    out = cross_rates_via_usd({"EUR": 1.10, "GBP": 1.27}, "USD")
    assert out["USD"] == pytest.approx(1.0)
    assert out["EUR"] == pytest.approx(1.0 / 1.10)
    assert out["GBP"] == pytest.approx(1.0 / 1.27)


def test_cross_rates_target_in_input():
    # target=EUR; USD→EUR rate is 1.10 (≈ "EUR per USD")
    # cross(USD→EUR) = 1.10
    # cross(GBP→EUR) = 1.10 / 1.27 ≈ 0.866
    out = cross_rates_via_usd({"EUR": 1.10, "GBP": 1.27}, "EUR")
    assert out["EUR"] == pytest.approx(1.0)
    assert out["USD"] == pytest.approx(1.10)
    assert out["GBP"] == pytest.approx(1.10 / 1.27)


def test_cross_rates_target_missing_returns_empty():
    out = cross_rates_via_usd({"EUR": 1.10}, "JPY")
    assert out == {}


def test_cross_rates_source_target_implicit_rate_one():
    out = cross_rates_via_usd({"EUR": 1.10}, "EUR")
    assert out["EUR"] == pytest.approx(1.0)


def test_cross_rates_numeric_precision():
    # target=EUR, USD→EUR=1.10 → EUR per USD = 1.10; USD per EUR ≈ 0.909
    # convert_totals will multiply USD-amount by the rate, so the rate
    # for USD source is "EUR per USD" = 1.10 (NOT 0.909).
    out = cross_rates_via_usd({"EUR": 1.10}, "EUR")
    assert out["USD"] == pytest.approx(1.10)


# ──────────────────────────  fetch_latest_rates  ──────────────────────


@patch("src.exchange_rates.requests.get")
def test_fetch_latest_rates_success_returns_bundle(mock_get):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "success": True,
        "base": "USD",
        "date": "2026-06-09",
        "rates": {"EUR": 1.10, "GBP": 1.27, "JPY": 150.0},
    }
    mock_get.return_value = resp

    bundle = fetch_latest_rates("USD")
    assert bundle is not None
    assert bundle.base == "USD"
    assert bundle.rate_date == date(2026, 6, 9)
    assert bundle.rates["EUR"] == 1.10
    assert bundle.rates["JPY"] == 150.0


@patch("src.exchange_rates.requests.get")
def test_fetch_latest_rates_api_success_false_returns_none(mock_get):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"success": False, "rates": {"EUR": 1.10}}
    mock_get.return_value = resp

    assert fetch_latest_rates("USD") is None


@patch("src.exchange_rates.requests.get")
def test_fetch_latest_rates_5xx_returns_none(mock_get):
    resp = MagicMock()
    resp.status_code = 503
    mock_get.return_value = resp

    assert fetch_latest_rates("USD") is None


@patch("src.exchange_rates.requests.get")
def test_fetch_latest_rates_network_error_returns_none(mock_get):
    mock_get.side_effect = requests.RequestException("boom")
    assert fetch_latest_rates("USD") is None


# ─────────────────────────────  get_rates_for  ────────────────────────


@patch("src.exchange_rates.fetch_latest_rates")
def test_get_rates_for_cache_miss_calls_api_and_writes_cache(mock_fetch, app):
    mock_fetch.return_value = RateBundle(
        base="USD",
        rates={"EUR": 1.10, "GBP": 1.27},
        rate_date=date(2026, 6, 9),
        fetched_at=datetime.utcnow(),
    )

    out = get_rates_for("USD", ["EUR", "GBP"], db_session=db.session)
    assert out["EUR"] == pytest.approx(1.10)
    assert out["GBP"] == pytest.approx(1.27)
    assert mock_fetch.called

    rows = ExchangeRateCache.query.all()
    targets = {r.target_currency for r in rows}
    assert targets == {"EUR", "GBP"}


@patch("src.exchange_rates.fetch_latest_rates")
def test_get_rates_for_cache_hit_skips_api(mock_fetch, app):
    db.session.add(ExchangeRateCache(
        base_currency="USD", target_currency="EUR",
        rate=1.10, rate_date=date(2026, 6, 9),
        fetched_at=datetime.utcnow(),
    ))
    db.session.commit()

    out = get_rates_for("USD", ["EUR"], db_session=db.session)
    assert out["EUR"] == pytest.approx(1.10)
    assert mock_fetch.called is False


@patch("src.exchange_rates.fetch_latest_rates")
def test_get_rates_for_stale_rows_trigger_refetch(mock_fetch, app):
    stale = datetime.utcnow() - timedelta(seconds=CACHE_TTL_SECONDS + 60)
    db.session.add(ExchangeRateCache(
        base_currency="USD", target_currency="EUR",
        rate=1.00, rate_date=date(2026, 6, 8),  # bogus old rate
        fetched_at=stale,
    ))
    db.session.commit()

    mock_fetch.return_value = RateBundle(
        base="USD",
        rates={"EUR": 1.15},
        rate_date=date(2026, 6, 9),
        fetched_at=datetime.utcnow(),
    )
    out = get_rates_for("USD", ["EUR"], db_session=db.session)
    assert out["EUR"] == pytest.approx(1.15)
    assert mock_fetch.called

    rows = ExchangeRateCache.query.filter_by(target_currency="EUR").all()
    assert any(abs(r.rate - 1.15) < 1e-6 for r in rows)


@patch("src.exchange_rates.fetch_latest_rates")
def test_get_rates_for_api_failure_returns_partial_from_cache(mock_fetch, app):
    db.session.add(ExchangeRateCache(
        base_currency="USD", target_currency="EUR",
        rate=1.10, rate_date=date(2026, 6, 9),
        fetched_at=datetime.utcnow(),
    ))
    db.session.commit()

    mock_fetch.return_value = None  # API down
    out = get_rates_for("USD", ["EUR", "GBP"], db_session=db.session)
    # EUR served from cache; GBP missing — that's fine, no exception.
    assert out.get("EUR") == pytest.approx(1.10)
    assert "GBP" not in out


@patch("src.exchange_rates.fetch_latest_rates")
def test_get_rates_for_missing_cache_table_returns_empty(mock_fetch, app):
    from sqlalchemy import text

    # Simulate a fresh deploy where db.create_all() hasn't run yet by
    # dropping the cache table mid-test. get_rates_for must degrade
    # to "no cache" and not crash.
    db.session.execute(text("DROP TABLE exchange_rate_cache"))
    db.session.commit()

    mock_fetch.return_value = None  # API also unavailable
    out = get_rates_for("USD", ["EUR"], db_session=db.session)
    assert out == {}
