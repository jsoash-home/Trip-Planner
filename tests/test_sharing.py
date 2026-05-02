"""Unit tests for src/sharing.py."""

from dataclasses import dataclass, field
from typing import List

from src.sharing import (
    SHARE_ROLE_CODES,
    can_edit,
    get_user_role_for_trip,
    is_owner,
    is_valid_email,
    normalize_email,
    parse_collaborator_form,
    role_satisfies,
)


@dataclass
class FakeUser:
    id: int
    email: str
    is_authenticated: bool = True


@dataclass
class FakeCollab:
    email: str
    role: str = "viewer"
    id: int = 0


@dataclass
class FakeTrip:
    id: int = 1
    owner_id: int = 1
    collaborators: List[FakeCollab] = field(default_factory=list)


# ─────────────────────────────  normalize / validate  ──────────────────────


def test_normalize_email_lowercases_and_strips():
    assert normalize_email("  Jane@EXAMPLE.com  ") == "jane@example.com"


def test_normalize_email_none_and_empty():
    assert normalize_email(None) == ""
    assert normalize_email("") == ""


def test_is_valid_email_basic_shapes():
    assert is_valid_email("a@b.co")
    assert is_valid_email("alice.smith+tag@sub.domain.example")
    assert not is_valid_email("nodomain")
    assert not is_valid_email("missing@dot")
    assert not is_valid_email("with space@example.com")
    assert not is_valid_email("")
    assert not is_valid_email(None)


# ─────────────────────────────  get_user_role_for_trip  ────────────────────


def test_owner_returns_owner():
    trip = FakeTrip(owner_id=42)
    user = FakeUser(id=42, email="owner@example.com")
    assert get_user_role_for_trip(trip, user) == "owner"


def test_collaborator_editor_returns_editor():
    trip = FakeTrip(owner_id=1, collaborators=[FakeCollab(email="jane@example.com", role="editor")])
    user = FakeUser(id=2, email="jane@example.com")
    assert get_user_role_for_trip(trip, user) == "editor"


def test_collaborator_viewer_returns_viewer():
    trip = FakeTrip(owner_id=1, collaborators=[FakeCollab(email="bob@example.com", role="viewer")])
    user = FakeUser(id=2, email="bob@example.com")
    assert get_user_role_for_trip(trip, user) == "viewer"


def test_collaborator_email_lookup_is_case_insensitive():
    trip = FakeTrip(owner_id=1, collaborators=[FakeCollab(email="jane@example.com", role="editor")])
    user = FakeUser(id=2, email="Jane@Example.COM")
    assert get_user_role_for_trip(trip, user) == "editor"


def test_non_collaborator_returns_none():
    trip = FakeTrip(owner_id=1, collaborators=[FakeCollab(email="jane@example.com")])
    user = FakeUser(id=2, email="stranger@example.com")
    assert get_user_role_for_trip(trip, user) is None


def test_unauthenticated_user_returns_none():
    trip = FakeTrip(owner_id=1)
    user = FakeUser(id=99, email="any@example.com", is_authenticated=False)
    assert get_user_role_for_trip(trip, user) is None


def test_none_user_returns_none():
    trip = FakeTrip(owner_id=1)
    assert get_user_role_for_trip(trip, None) is None


def test_user_with_blank_email_returns_none():
    trip = FakeTrip(owner_id=1, collaborators=[FakeCollab(email="", role="viewer")])
    user = FakeUser(id=2, email="")
    assert get_user_role_for_trip(trip, user) is None


def test_corrupt_role_downgrades_to_viewer():
    # Defensive — a corrupt role shouldn't ever happen but shouldn't crash.
    trip = FakeTrip(owner_id=1, collaborators=[FakeCollab(email="x@y.com", role="superadmin")])
    user = FakeUser(id=2, email="x@y.com")
    assert get_user_role_for_trip(trip, user) == "viewer"


# ─────────────────────────────  role_satisfies + helpers  ──────────────────


def test_owner_satisfies_all_levels():
    assert role_satisfies("owner", "viewer")
    assert role_satisfies("owner", "editor")
    assert role_satisfies("owner", "owner")


def test_editor_satisfies_viewer_and_editor_but_not_owner():
    assert role_satisfies("editor", "viewer")
    assert role_satisfies("editor", "editor")
    assert not role_satisfies("editor", "owner")


def test_viewer_only_satisfies_viewer():
    assert role_satisfies("viewer", "viewer")
    assert not role_satisfies("viewer", "editor")
    assert not role_satisfies("viewer", "owner")


def test_none_satisfies_nothing():
    assert not role_satisfies(None, "viewer")
    assert not role_satisfies(None, "owner")


def test_can_edit_helper():
    assert can_edit("owner")
    assert can_edit("editor")
    assert not can_edit("viewer")
    assert not can_edit(None)


def test_is_owner_helper():
    assert is_owner("owner")
    assert not is_owner("editor")
    assert not is_owner("viewer")
    assert not is_owner(None)


# ─────────────────────────────  parse_collaborator_form  ───────────────────


def test_parse_form_valid():
    data, errors = parse_collaborator_form(
        {"email": "Jane@example.com", "role": "editor"},
        owner_email="owner@example.com",
    )
    assert errors == []
    assert data["email"] == "jane@example.com"
    assert data["role"] == "editor"


def test_parse_form_missing_email():
    _, errors = parse_collaborator_form(
        {"email": "", "role": "viewer"},
        owner_email="owner@example.com",
    )
    assert any("Email" in e for e in errors)


def test_parse_form_invalid_email():
    _, errors = parse_collaborator_form(
        {"email": "not-an-email", "role": "viewer"},
        owner_email="owner@example.com",
    )
    assert any("doesn't look right" in e for e in errors)


def test_parse_form_invalid_role_falls_back_to_viewer():
    data, errors = parse_collaborator_form(
        {"email": "jane@example.com", "role": "admin"},
        owner_email="owner@example.com",
    )
    assert any("Viewer or Editor" in e for e in errors)
    assert data["role"] == "viewer"


def test_parse_form_rejects_owners_own_email():
    _, errors = parse_collaborator_form(
        {"email": "OWNER@example.com", "role": "viewer"},
        owner_email="owner@example.com",
    )
    assert any("trip owner" in e for e in errors)


def test_parse_form_rejects_duplicate_email():
    _, errors = parse_collaborator_form(
        {"email": "Jane@Example.com", "role": "editor"},
        owner_email="owner@example.com",
        existing_emails=["jane@example.com"],
    )
    assert any("already on the share list" in e for e in errors)


def test_parse_form_blank_role_silently_defaults_to_viewer():
    # Blank role (e.g. dropdown not interacted with) is the friendliest
    # default — silently treat as viewer, no error.
    data, errors = parse_collaborator_form(
        {"email": "jane@example.com", "role": ""},
        owner_email="owner@example.com",
    )
    assert errors == []
    assert data["role"] == "viewer"


def test_share_role_codes_unchanged():
    assert SHARE_ROLE_CODES == frozenset({"viewer", "editor"})
