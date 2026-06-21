"""Shared classification of a provider's raw ``status`` text into one of three
display buckets, so the search card's status pill and the map marker colour stay
in agreement.

``status`` is free-form scraped text that varies by state ("Licensed",
"Provisional License", "Pending", ...), so the mapping is keyword-based and
checks the cautionary keywords first — a "Provisional License" is attention, not
active, even though it contains "license".
"""

from __future__ import annotations

# Cautionary states win over the "looks licensed" keywords below. The negated
# phrases ("not licensed", ...) come first so a status like "NOT LICENSED" is not
# read as active just because it contains the substring "licensed".
_WARN_KEYWORDS = (
    "not licensed",
    "unlicensed",
    "not active",
    "no license",
    "provisional",
    "probation",
    "pending",
    "suspend",
    "revok",
    "closed",
    "expired",
    "denied",
    "inactive",
    "violation",
    "alert",
)
_ACTIVE_KEYWORDS = (
    "licensed",
    "license",
    "active",
    "open",
    "approved",
    "permitted",
    "registr",
    "good standing",
    "compliant",
)


def status_bucket(status: str | None) -> str:
    """Return ``"active"``, ``"warn"``, or ``"neutral"`` for a raw status string."""
    text = (status or "").lower()
    if not text:
        return "neutral"
    if any(keyword in text for keyword in _WARN_KEYWORDS):
        return "warn"
    if any(keyword in text for keyword in _ACTIVE_KEYWORDS):
        return "active"
    return "neutral"
