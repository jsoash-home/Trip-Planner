"""guide_builder — DB read + file IO + share-token plumbing for the trip-guide skill.

The skill (.claude/skills/trip-guide/SKILL.md) calls into this module. Helpers
are deliberately small and tested. HTML composition lives in the skill, not here.
"""

import json
import logging
import os
import uuid
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

GUIDES_DIR = Path("data/guides")
CONFIG_SCHEMA_VERSION = 1
SECTION_KEYS = (
    "day_by_day",
    "field_guide",
    "things_to_do",
    "weather",
    "history",
    "fun_facts",
    "food",
)
GUIDE_STORAGE = os.getenv("GUIDE_STORAGE", "filesystem")


class GuideError(Exception):
    """Base error for guide_builder."""


class TripNotFound(GuideError):
    """Trip ID does not exist."""


class GuideMissing(GuideError):
    """No guide HTML found for this trip."""


@dataclass
class GuideConfig:
    schema_version: int
    trip_id: int
    sections: list
    palette: dict
    last_generated_at: Optional[str]
