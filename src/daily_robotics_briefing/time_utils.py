from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

US_EASTERN_TIMEZONE = ZoneInfo("America/Cupertino")


def eastern_today() -> date:
    """Return today's date in US Eastern time (EST/EDT)."""
    return datetime.now(US_EASTERN_TIMEZONE).date()

