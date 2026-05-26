"""
src/sharing.py

Pure helpers for trip sharing — email normalization, role lookup, role
satisfaction (`role >= required`), and form parsing.

No DB, no Flask imports. The route layer in app.py owns the DB lookups
and the abort(404) on access denial.
"""

import logging
import re
from typing import Any, Dict, List, Mapping, Optional, Tuple

logger = logging.getLogger(__name__)


# Roles, lowest first. Owner is always implicit (Trip.owner_id), never stored.
SHARE_ROLES: Tuple[Tuple[str, str], ...] = (
    ("viewer", "Viewer — can see this trip"),
    ("editor", "Editor — can add, change, and remove items"),
)
SHARE_ROLE_CODES = frozenset(c for c, _ in SHARE_ROLES)
SHARE_ROLE_LABELS = {c: lbl for c, lbl in SHARE_ROLES}

# Levels for role_satisfies(). Higher number = more access.
_ROLE_LEVELS = {"viewer": 1, "editor": 2, "owner": 3}

# Pragmatic email regex — non-empty local part, an @, non-empty domain
# with at least one dot. Permissive on purpose; the ground truth is
# whether the inviting user can sign in with that Google address.
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def normalize_email(email: Optional[str]) -> str:
    """Lowercase + strip; empty input returns ''."""
    if email is None:
        return ""
    return email.strip().lower()


def is_valid_email(email: Optional[str]) -> bool:
    """Loose email shape check. Non-empty local + domain with at least one dot."""
    if not email:
        return False
    return _EMAIL_RE.match(email) is not None


def get_user_role_for_trip(trip, user) -> Optional[str]:
    """
    Return the access role for `user` on `trip`, or None if no access.

    Possible return values: "owner", "editor", "viewer", or None.

    Pure-ish: assumes `trip.collaborators` is loaded (SQLAlchemy fetches
    lazily on first access — which is fine inside a Flask request).
    """
    if user is None:
        return None
    if not getattr(user, "is_authenticated", False):
        return None
    if getattr(trip, "owner_id", None) == getattr(user, "id", object()):
        return "owner"

    user_email = normalize_email(getattr(user, "email", ""))
    if not user_email:
        return None

    for collab in getattr(trip, "collaborators", []) or []:
        if normalize_email(getattr(collab, "email", "")) == user_email:
            role = getattr(collab, "role", None)
            if role in SHARE_ROLE_CODES:
                return role
            # Defensive: a corrupt role string downgrades to viewer.
            logger.warning(
                "Collaborator id=%s has unrecognised role %r — treating as viewer",
                getattr(collab, "id", "?"), role,
            )
            return "viewer"

    return None


def role_satisfies(actual: Optional[str], required: str) -> bool:
    """
    True if `actual` is at least as privileged as `required`.

    Hierarchy: viewer < editor < owner. None never satisfies anything.
    """
    if actual is None:
        return False
    return _ROLE_LEVELS.get(actual, 0) >= _ROLE_LEVELS.get(required, 0)


def can_edit(role: Optional[str]) -> bool:
    """Convenience: True if role is editor or owner."""
    return role_satisfies(role, "editor")


def is_owner(role: Optional[str]) -> bool:
    """Convenience: True if role is owner."""
    return role == "owner"


def parse_collaborator_form(
    form: Mapping[str, str],
    *,
    owner_email: str,
    existing_emails: Optional[List[str]] = None,
) -> Tuple[Dict[str, Any], Dict[str, str]]:
    """
    Pull and validate fields for adding a collaborator.

    Reject the owner's own email (they're already the owner) and emails
    that are already in `existing_emails` (duplicate adds — caller can
    instead update the existing role).

    Returns (cleaned_data, field_errors). field_errors is keyed by form
    field name (e.g. `"email"`, `"role"`); an empty dict means valid.
    Owner-self and duplicate-email messages attach to `"email"`.
    """
    field_errors: Dict[str, str] = {}

    email = normalize_email(form.get("email"))
    if not email:
        field_errors["email"] = "Email is required."
    elif not is_valid_email(email):
        field_errors["email"] = "That email doesn't look right (must contain @ and a domain)."

    role = (form.get("role") or "viewer").strip().lower()
    if role not in SHARE_ROLE_CODES:
        field_errors["role"] = "Role must be Viewer or Editor."
        role = "viewer"

    if email and email == normalize_email(owner_email):
        field_errors["email"] = "You're the trip owner already — no need to share with yourself."

    if email and existing_emails:
        existing_normed = {normalize_email(e) for e in existing_emails}
        if email in existing_normed:
            field_errors["email"] = (
                "That email is already on the share list — remove it first if you want a different role."
            )

    return {"email": email, "role": role}, field_errors
