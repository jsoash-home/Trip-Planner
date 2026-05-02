"""
src/currency.py

Currency support for the Vacation Planner.

Two pieces:
  - SUPPORTED_CURRENCIES — the list shown in the trip form's dropdown
  - format_money(amount, code) — turn a number + code into a display string

Pure functions only. No DB, no network, no Flask imports.
"""

from typing import Optional, Tuple, Union


# Tuples of (ISO 4217 code, English display name). Order matters — this is
# the order the dropdown shows them in. USD is first because it's the
# fallback default everywhere in the app.
SUPPORTED_CURRENCIES: Tuple[Tuple[str, str], ...] = (
    ("USD", "US Dollar"),
    ("EUR", "Euro"),
    ("GBP", "British Pound"),
    ("CAD", "Canadian Dollar"),
    ("AUD", "Australian Dollar"),
    ("JPY", "Japanese Yen"),
    ("MXN", "Mexican Peso"),
    ("CHF", "Swiss Franc"),
    ("NZD", "New Zealand Dollar"),
    ("INR", "Indian Rupee"),
    ("BRL", "Brazilian Real"),
    ("KRW", "South Korean Won"),
    ("CNY", "Chinese Yuan"),
    ("SEK", "Swedish Krona"),
    ("NOK", "Norwegian Krone"),
    ("DKK", "Danish Krone"),
    ("ZAR", "South African Rand"),
    ("AED", "UAE Dirham"),
    ("THB", "Thai Baht"),
    ("SGD", "Singapore Dollar"),
    ("HKD", "Hong Kong Dollar"),
)

SUPPORTED_CURRENCY_CODES = frozenset(code for code, _ in SUPPORTED_CURRENCIES)

# Currencies traditionally written without decimal subdivisions.
_NO_DECIMAL_CODES = frozenset({"JPY", "KRW"})

# Display symbols. Codes not in this map fall back to "<CODE> " as the prefix.
_SYMBOLS = {
    "USD": "$",   "EUR": "€",   "GBP": "£",   "CAD": "CA$",
    "AUD": "A$",  "JPY": "¥",   "MXN": "MX$", "CHF": "CHF ",
    "NZD": "NZ$", "INR": "₹",   "BRL": "R$",  "KRW": "₩",
    "CNY": "¥",   "SEK": "kr ", "NOK": "kr ", "DKK": "kr ",
    "ZAR": "R ",  "AED": "AED ","THB": "฿",   "SGD": "S$",
    "HKD": "HK$",
}


def is_valid_currency(code: Optional[str]) -> bool:
    """True if the code is a supported ISO 4217 currency code."""
    if not code:
        return False
    return code.upper() in SUPPORTED_CURRENCY_CODES


def format_money(amount: Optional[Union[int, float]], code: str) -> str:
    """
    Format an amount with its currency symbol.

    Examples:
      format_money(1234.5, "USD") -> "$1,234.50"
      format_money(1234, "JPY")   -> "¥1,234"
      format_money(None, "USD")   -> "—"
      format_money(0, "EUR")      -> "€0.00"

    Unknown codes still render: format_money(1, "ZZZ") -> "ZZZ 1.00".
    Use is_valid_currency() up front if you want to validate.
    """
    if amount is None:
        return "—"
    code_upper = (code or "USD").upper()
    symbol = _SYMBOLS.get(code_upper, code_upper + " ")
    if code_upper in _NO_DECIMAL_CODES:
        return f"{symbol}{int(round(amount)):,}"
    return f"{symbol}{amount:,.2f}"
