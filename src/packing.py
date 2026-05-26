"""
src/packing.py

Pure helpers for the packing list — category metadata, the seed list of
universal items used to pre-populate every new trip, form parsing, and
display grouping. No DB, no Flask imports.
"""

import logging
from typing import Any, Dict, Iterable, List, Mapping, Tuple

logger = logging.getLogger(__name__)


# (code, label, emoji) — order is the display order on the packing page.
PACKING_CATEGORIES: Tuple[Tuple[str, str, str], ...] = (
    ("documents",   "Documents",   "📄"),
    ("clothing",    "Clothing",    "👕"),
    ("toiletries",  "Toiletries",  "🧴"),
    ("electronics", "Electronics", "🔌"),
    ("other",       "Other",       "📦"),
)

PACKING_CATEGORY_CODES = frozenset(c for c, _, _ in PACKING_CATEGORIES)
PACKING_CATEGORY_LABELS = {c: lbl for c, lbl, _ in PACKING_CATEGORIES}
PACKING_CATEGORY_EMOJIS = {c: emoji for c, _, emoji in PACKING_CATEGORIES}


# Twelve universal items every trip starts with, so a fresh packing page
# isn't a blank slate. Users can keep, edit, or delete any of them.
DEFAULT_PACKING_ITEMS: Tuple[Dict[str, str], ...] = (
    {"category": "documents",   "name": "Passport / ID"},
    {"category": "documents",   "name": "Wallet"},
    {"category": "documents",   "name": "Travel insurance info"},
    {"category": "electronics", "name": "Phone"},
    {"category": "electronics", "name": "Phone charger"},
    {"category": "electronics", "name": "Headphones"},
    {"category": "toiletries",  "name": "Toothbrush + toothpaste"},
    {"category": "toiletries",  "name": "Medications"},
    {"category": "clothing",    "name": "Underwear / socks"},
    {"category": "clothing",    "name": "Pajamas"},
    {"category": "clothing",    "name": "Comfortable walking shoes"},
    {"category": "other",       "name": "Reusable water bottle"},
)


def category_label(code: str) -> str:
    """Display label for a packing category code; falls back to the code."""
    return PACKING_CATEGORY_LABELS.get(code, code)


def category_emoji(code: str) -> str:
    """Display emoji for a packing category code; falls back to a generic box."""
    return PACKING_CATEGORY_EMOJIS.get(code, "📦")


def parse_packing_form(form: Mapping[str, str]) -> Tuple[Dict[str, Any], Dict[str, str]]:
    """
    Pull and validate packing fields from a submitted HTML form.

    Returns (cleaned_data, field_errors). field_errors is keyed by form
    field name; an empty dict means the form is valid.
    """
    field_errors: Dict[str, str] = {}

    name = (form.get("name") or "").strip()
    if not name:
        field_errors["name"] = "Name is required."

    category = (form.get("category") or "other").strip().lower()
    if category not in PACKING_CATEGORY_CODES:
        field_errors["category"] = "Category is not valid."
        category = "other"

    notes = (form.get("notes") or "").strip() or None
    # Browsers omit unchecked checkboxes from the form payload, so a missing
    # key means False here.
    packed = (form.get("packed") or "").strip().lower() in ("on", "true", "1", "yes")

    data: Dict[str, Any] = {
        "name": name,
        "category": category,
        "packed": packed,
        "notes": notes,
    }
    return data, field_errors


def packing_form_values(item) -> Dict[str, str]:
    """
    Convert a PackingItem row into form field strings for the edit page.

    Returns an empty dict when item is None — used by the new-item form.
    """
    if item is None:
        return {}
    return {
        "name": item.name or "",
        "category": item.category or "other",
        "notes": item.notes or "",
        "packed": "on" if item.packed else "",
    }


def group_packing_by_category(items: Iterable) -> List[Tuple[str, str, str, List]]:
    """
    Split packing items into display groups in canonical category order.

    Returns [(code, label, emoji, items_in_category), ...]. Empty
    categories are omitted. Within a group, items sort with unpacked
    first (so the user sees what's still to do at the top), then
    alphabetically by name.
    """
    by_cat: Dict[str, List] = {}
    for it in items:
        by_cat.setdefault(getattr(it, "category", None) or "other", []).append(it)

    out: List[Tuple[str, str, str, List]] = []
    for code, label, emoji in PACKING_CATEGORIES:
        cat_items = by_cat.get(code)
        if not cat_items:
            continue
        # Unpacked items first, then by name (case-insensitive).
        cat_items.sort(key=lambda x: (
            bool(getattr(x, "packed", False)),
            (getattr(x, "name", "") or "").lower(),
        ))
        out.append((code, label, emoji, cat_items))
    return out


def packing_progress(items: Iterable) -> Tuple[int, int, int]:
    """
    Return (packed_count, total_count, percent_int) for the progress bar.

    percent_int is 0–100; when total == 0, returns (0, 0, 0).
    """
    items_list = list(items)
    total = len(items_list)
    if total == 0:
        return (0, 0, 0)
    packed = sum(1 for it in items_list if getattr(it, "packed", False))
    percent = round((packed / total) * 100)
    return (packed, total, percent)
