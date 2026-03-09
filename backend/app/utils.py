"""Shared utility functions."""
from __future__ import annotations

from app.schemas import StalenessLevel

_WARN_MINUTES = 30
_CRIT_MINUTES = 60
_UNAVAIL_HOURS = 4


def staleness_level(minutes: float | None) -> StalenessLevel:
    """Determine staleness level based on minutes since last update."""
    if minutes is None:
        return "unavailable"
    if minutes < _WARN_MINUTES:
        return "fresh"
    if minutes < _CRIT_MINUTES:
        return "warning"
    if minutes < _UNAVAIL_HOURS * 60:
        return "critical"
    return "unavailable"
