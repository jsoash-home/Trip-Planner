"""Unit tests for src/packing.py."""

from dataclasses import dataclass
from typing import Optional

from src.packing import (
    DEFAULT_PACKING_ITEMS,
    PACKING_CATEGORIES,
    PACKING_CATEGORY_CODES,
    category_emoji,
    category_label,
    group_packing_by_category,
    packing_form_values,
    packing_progress,
    parse_packing_form,
)


@dataclass
class FakeItem:
    """Stand-in for a PackingItem row."""

    id: int
    name: str
    category: str = "other"
    packed: bool = False
    notes: Optional[str] = None


# ─────────────────────────────  metadata + defaults  ───────────────────────


def test_categories_codes_set_matches_tuple():
    assert PACKING_CATEGORY_CODES == frozenset(c for c, _, _ in PACKING_CATEGORIES)


def test_default_packing_items_uses_only_known_categories():
    for d in DEFAULT_PACKING_ITEMS:
        assert d["category"] in PACKING_CATEGORY_CODES, d


def test_default_packing_items_has_at_least_a_dozen():
    assert len(DEFAULT_PACKING_ITEMS) >= 12


def test_category_label_known_and_unknown():
    assert category_label("clothing") == "Clothing"
    assert category_label("zzz") == "zzz"


def test_category_emoji_known_and_unknown():
    assert category_emoji("documents") == "📄"
    assert category_emoji("zzz") == "📦"


# ─────────────────────────────  parse_packing_form  ────────────────────────


def _valid_form(**overrides):
    base = {
        "name": "Sunglasses",
        "category": "other",
        "notes": "polarized",
        "packed": "",
    }
    base.update(overrides)
    return base


def test_parse_packing_form_valid_no_errors():
    data, field_errors = parse_packing_form(_valid_form())
    assert field_errors == {}
    assert data["name"] == "Sunglasses"
    assert data["category"] == "other"
    assert data["packed"] is False


def test_parse_packing_form_missing_name_errors():
    _, field_errors = parse_packing_form(_valid_form(name=""))
    assert "name" in field_errors


def test_parse_packing_form_unknown_category_errors_and_falls_back():
    data, field_errors = parse_packing_form(_valid_form(category="zzz"))
    assert "category" in field_errors
    assert data["category"] == "other"


def test_parse_packing_form_packed_checkbox_on_means_true():
    data, _ = parse_packing_form(_valid_form(packed="on"))
    assert data["packed"] is True


def test_parse_packing_form_packed_omitted_means_false():
    data, _ = parse_packing_form({"name": "Hat", "category": "clothing"})
    assert data["packed"] is False


def test_parse_packing_form_strips_whitespace():
    data, _ = parse_packing_form(_valid_form(name="  Hat  "))
    assert data["name"] == "Hat"


def test_parse_packing_form_blank_notes_becomes_none():
    data, _ = parse_packing_form(_valid_form(notes=""))
    assert data["notes"] is None


# ─────────────────────────────  packing_form_values  ───────────────────────


def test_packing_form_values_none_returns_empty_dict():
    assert packing_form_values(None) == {}


def test_packing_form_values_renders_fields():
    item = FakeItem(id=1, name="Hat", category="clothing", packed=True, notes="wide brim")
    out = packing_form_values(item)
    assert out["name"] == "Hat"
    assert out["category"] == "clothing"
    assert out["packed"] == "on"
    assert out["notes"] == "wide brim"


def test_packing_form_values_unpacked_omits_packed():
    item = FakeItem(id=1, name="Hat", category="clothing", packed=False)
    out = packing_form_values(item)
    assert out["packed"] == ""


# ─────────────────────────────  group_packing_by_category  ─────────────────


def test_group_empty_input_returns_empty_list():
    assert group_packing_by_category([]) == []


def test_group_canonical_order():
    items = [
        FakeItem(id=1, name="Phone", category="electronics"),
        FakeItem(id=2, name="Passport", category="documents"),
        FakeItem(id=3, name="Hat", category="clothing"),
    ]
    out = group_packing_by_category(items)
    codes = [c for c, _, _, _ in out]
    # Display order from PACKING_CATEGORIES: documents, clothing, ..., electronics.
    assert codes == ["documents", "clothing", "electronics"]


def test_group_unpacked_first_then_alphabetical():
    items = [
        FakeItem(id=1, name="Banana", category="other", packed=True),
        FakeItem(id=2, name="Apple",  category="other", packed=False),
        FakeItem(id=3, name="Cherry", category="other", packed=False),
    ]
    out = group_packing_by_category(items)
    names = [it.name for it in out[0][3]]
    # Apple + Cherry (unpacked, alphabetical) before Banana (packed).
    assert names == ["Apple", "Cherry", "Banana"]


def test_group_unknown_category_dropped():
    items = [FakeItem(id=1, name="Mystery", category="spaceship")]
    out = group_packing_by_category(items)
    # Unknown categories aren't in PACKING_CATEGORIES so they don't appear.
    assert out == []


# ─────────────────────────────  packing_progress  ──────────────────────────


def test_packing_progress_empty_returns_zeros():
    assert packing_progress([]) == (0, 0, 0)


def test_packing_progress_nothing_packed_yet():
    items = [FakeItem(id=1, name="A"), FakeItem(id=2, name="B")]
    assert packing_progress(items) == (0, 2, 0)


def test_packing_progress_partial():
    items = [
        FakeItem(id=1, name="A", packed=True),
        FakeItem(id=2, name="B", packed=False),
        FakeItem(id=3, name="C", packed=True),
        FakeItem(id=4, name="D", packed=False),
    ]
    assert packing_progress(items) == (2, 4, 50)


def test_packing_progress_all_packed_is_100():
    items = [FakeItem(id=1, name="A", packed=True)]
    assert packing_progress(items) == (1, 1, 100)


def test_packing_progress_rounds_correctly():
    # 2 of 3 = 66.67 → rounds to 67
    items = [
        FakeItem(id=1, name="A", packed=True),
        FakeItem(id=2, name="B", packed=True),
        FakeItem(id=3, name="C", packed=False),
    ]
    _, _, percent = packing_progress(items)
    assert percent == 67
