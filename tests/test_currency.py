"""Unit tests for src/currency.py."""

from src.currency import (
    SUPPORTED_CURRENCIES,
    SUPPORTED_CURRENCY_CODES,
    format_money,
    is_valid_currency,
)


def test_supported_currencies_starts_with_usd():
    # USD is the app-wide default; if it isn't first, the dropdown shows
    # something else as the default selection on a fresh form.
    assert SUPPORTED_CURRENCIES[0][0] == "USD"


def test_supported_currency_codes_set_matches_tuple():
    assert SUPPORTED_CURRENCY_CODES == frozenset(c for c, _ in SUPPORTED_CURRENCIES)


# ─────────────────────────────  is_valid_currency  ─────────────────────────


def test_is_valid_currency_accepts_known_code():
    assert is_valid_currency("USD")
    assert is_valid_currency("eur")  # case-insensitive
    assert is_valid_currency(" GBP ".strip())


def test_is_valid_currency_rejects_unknown():
    assert not is_valid_currency("ZZZ")
    assert not is_valid_currency("")
    assert not is_valid_currency(None)


# ─────────────────────────────  format_money  ──────────────────────────────


def test_format_money_usd_with_decimals():
    assert format_money(1234.5, "USD") == "$1,234.50"


def test_format_money_zero_renders_with_decimals():
    assert format_money(0, "EUR") == "€0.00"


def test_format_money_jpy_has_no_decimals():
    assert format_money(1234, "JPY") == "¥1,234"


def test_format_money_krw_has_no_decimals():
    assert format_money(50000, "KRW") == "₩50,000"


def test_format_money_none_returns_em_dash():
    assert format_money(None, "USD") == "—"


def test_format_money_unknown_code_falls_back_to_prefix():
    assert format_money(1, "XYZ") == "XYZ 1.00"


def test_format_money_lowercases_then_uppercases_code():
    assert format_money(10, "usd") == "$10.00"


def test_format_money_large_number_has_commas():
    assert format_money(1234567.89, "USD") == "$1,234,567.89"
