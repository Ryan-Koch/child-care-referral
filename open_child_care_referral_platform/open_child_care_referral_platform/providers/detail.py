"""View-model helpers for the styled provider detail page.

The detail template is mostly presentation; the *state-specific* decisions —
which quality-rating system a provider belongs to (or none), how to read its
inspection findings, which fields are worth showing — live here as small, pure
functions that take a :class:`~...providers.models.Provider` and return plain
dicts/lists. Keeping that logic in Python (like ``status.py``) makes it testable
and keeps the per-state branching out of the templates.

Only three states are loaded today (``"NY"``, ``"VA"``, ``"South Carolina"`` —
note the inconsistent codes, mirrored from ``views.py``). Everything degrades to
a sensible generic shape for any other ``source_state``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any

if TYPE_CHECKING:
    from collections.abc import Iterable

    from open_child_care_referral_platform.providers.models import Inspection
    from open_child_care_referral_platform.providers.models import Provider

NY = "NY"
VA = "VA"
SOUTH_CAROLINA = "South Carolina"

# Per-state display profile: friendly name + the licensing agency cited in the
# Compliance tab's context note. Unknown states fall back to a generic profile.
STATE_PROFILES: dict[str, dict[str, str]] = {
    NY: {
        "name": "New York",
        "agency": "the NYS Office of Children & Family Services",
    },
    VA: {
        "name": "Virginia",
        "agency": "the Virginia Department of Education",
    },
    SOUTH_CAROLINA: {
        "name": "South Carolina",
        "agency": "the SC Department of Social Services",
    },
}


def state_profile(provider: Provider) -> dict[str, str]:
    """Friendly name + licensing agency for a provider's ``source_state``."""
    code = provider.source_state or ""
    known = STATE_PROFILES.get(code)
    if known:
        return {"code": code, **known}
    return {
        "code": code,
        "name": code or "Unknown state",
        "agency": "the state's child care licensing agency",
    }


# ---------------------------------------------------------------------------
# Small parsing helpers
# ---------------------------------------------------------------------------
def _to_int(value: object) -> int | None:
    """Parse scraped numeric text (tolerating commas) to int, else ``None``."""
    try:
        return int(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _truthy(value: object) -> bool:
    """True for scraped affirmatives ("Yes"/"true"/"1"); false otherwise."""
    return str(value).strip().lower() in {"yes", "true", "y", "1"}


def _present(value: object) -> bool:
    """True when a value is worth rendering (not None/empty string/list/dict)."""
    return value not in (None, "", [], {})


# Short acronyms that should stay upper-cased when a state_data key is humanized.
_ACRONYMS = {"abc", "id", "shsi", "qris", "sutq", "ssn", "url", "ein", "fdc"}
_STATE_PREFIXES = ("ny_", "va_", "sc_", "oh_", "tx_", "ca_", "md_")


def humanize_state_key(key: str) -> str:
    """Turn a ``state_data`` key into a readable label.

    Strips the leading state prefix, de-snake-cases, and title-cases each word,
    keeping known acronyms upper (``sc_abc_quality_rating`` -> "ABC Quality
    Rating", ``va_ID`` -> "ID").
    """
    name = key
    lowered = key.lower()
    for prefix in _STATE_PREFIXES:
        if lowered.startswith(prefix):
            name = key[len(prefix) :]
            break
    words = [
        word.upper() if word.lower() in _ACRONYMS else word.capitalize()
        for word in name.replace("_", " ").split()
    ]
    return " ".join(words) or key


def _format_value(value: object) -> str:
    """Render a scalar state value for display (lists joined, rest stringified)."""
    if isinstance(value, (list, tuple)):
        return ", ".join(str(item) for item in value)
    return str(value)


# ---------------------------------------------------------------------------
# Quality rating (state-conditional)
# ---------------------------------------------------------------------------
# South Carolina ABC Quality grades that count as an actual rating. "P"
# (Pending) and "E" (Exempt) mean the program is enrolled but not graded.
_SC_RATED_GRADES = {"A+", "A", "B+", "B", "C"}
_SC_UNRATED_LABELS = {"P": "Pending", "E": "Exempt"}
_SC_BLURB = (
    "South Carolina's ABC Quality program rates participating providers on "
    "standards above basic licensing, from C up to A+."
)
_VA_BLURB = (
    "Virginia Quality measures programs on teacher-child interactions and "
    "curriculum, summarized as a single quality level."
)


def quality_summary(provider: Provider) -> dict[str, Any] | None:
    """Quality-rating view-model, or ``None`` when the state runs no QRIS.

    ``None`` means "this state has no statewide quality system" (NY / unknown),
    so the template shows the no-system message. A returned dict always carries
    ``is_rated``; when False the program exists but this provider isn't graded.
    """
    state = provider.source_state or ""
    state_data = provider.state_data or {}
    if state == SOUTH_CAROLINA:
        return _sc_quality(state_data)
    if state == VA:
        return _va_quality(state_data)
    return None


def _sc_quality(state_data: dict[str, Any]) -> dict[str, Any]:
    rating = str(state_data.get("sc_abc_quality_rating") or "").strip()
    is_rated = rating in _SC_RATED_GRADES
    history = [
        {"date": str(item.get("date", "")), "rating": str(item.get("rating", ""))}
        for item in state_data.get("sc_abc_rating_history") or []
        if isinstance(item, dict)
    ]
    return {
        "system": "ABC Quality",
        "kind": "grade",
        "is_rated": is_rated,
        "rating": rating if is_rated else "",
        "status_label": _SC_UNRATED_LABELS.get(rating, "Not yet rated"),
        "history": history,
        "blurb": _SC_BLURB,
    }


def _va_quality(state_data: dict[str, Any]) -> dict[str, Any]:
    rating = str(state_data.get("va_quality_rating") or "").strip()
    return {
        "system": "Virginia Quality",
        "kind": "tier",
        "is_rated": bool(rating),
        "rating": rating,
        "status_label": "Not yet rated",
        "total_points": str(state_data.get("va_total_points") or "").strip(),
        "domains": _va_domains(state_data),
        "blurb": _VA_BLURB,
    }


def _va_domains(state_data: dict[str, Any]) -> list[dict[str, str]]:
    """Point-score bars for VA's quality domains, scaled to the largest domain."""
    pairs = (
        ("Teacher-child interactions", state_data.get("va_interactions_points")),
        ("Curriculum", state_data.get("va_curriculum_points")),
    )
    parsed = [(label, _to_int(raw)) for label, raw in pairs]
    present = [(label, points) for label, points in parsed if points is not None]
    if not present:
        return []
    top = max(points for _, points in present) or 1
    return [
        {"label": label, "points": str(points), "pct": f"{round(points / top * 100)}%"}
        for label, points in present
    ]


# ---------------------------------------------------------------------------
# Compliance and inspection findings, state by state
# ---------------------------------------------------------------------------
# Recognized SC deficiency severities; anything else renders as "unrated".
_SEVERITY_LEVELS = {"high", "medium", "low"}


def compliance_summary(
    provider: Provider,
    inspections: Iterable[Inspection],
) -> dict[str, Any] | None:
    """Inspection-history view-model, or ``None`` when there are no records.

    SC inspections carry parseable per-deficiency findings; VA inspections only
    flag whether violations were found, so they render as flat rows. ``None``
    tells the caller to hide the Compliance tab entirely (e.g. NY has none).
    """
    records = list(inspections)
    if not records:
        return None
    state = provider.source_state or ""
    if state == SOUTH_CAROLINA:
        return _sc_compliance(records)
    if state == VA:
        return _va_compliance(records)
    return _generic_compliance(records)


def _stat(label: str, value: object, *, warn: bool = False) -> dict[str, Any]:
    return {"label": label, "value": str(value), "warn": warn}


def _sc_compliance(records: list[Inspection]) -> dict[str, Any]:
    rows = [_sc_row(inspection) for inspection in records]
    open_count = sum(row["open_count"] for row in rows)
    return {
        "kind": "sc",
        "expandable": True,
        "stats": [
            _stat("Inspections on record", len(rows)),
            _stat("Open deficiencies", open_count, warn=open_count > 0),
            _stat("Most recent", records[0].date or "-"),
        ],
        "rows": rows,
    }


def _sc_row(inspection: Inspection) -> dict[str, Any]:
    state_data = inspection.state_data or {}
    findings = [
        _sc_finding(item)
        for item in state_data.get("sc_deficiencies") or []
        if isinstance(item, dict)
    ]
    open_count = sum(1 for finding in findings if not finding["resolved"])
    count = len(findings)
    if count == 0:
        summary = "No deficiencies cited"
    elif open_count == 0:
        summary = f"{count} deficiency(ies) cited - all resolved"
    else:
        summary = f"{count} deficiency(ies) cited - {open_count} open"
    return {
        "type": inspection.type or "Inspection",
        "date": inspection.date or "",
        "findings": findings,
        "deficiency_count": count,
        "open_count": open_count,
        "clean": count == 0,
        "summary": summary,
    }


def _sc_finding(item: dict[str, Any]) -> dict[str, Any]:
    severity = str(item.get("severity") or "").strip()
    level = severity.lower()
    resolved = _truthy(item.get("resolved"))
    return {
        "type": str(item.get("deficiency_type") or "Deficiency"),
        "severity": severity or "Unrated",
        "severity_level": level if level in _SEVERITY_LEVELS else "unrated",
        "resolved": resolved,
        "status_label": "Resolved" if resolved else "Open",
        "date_resolved": str(item.get("date_resolved") or ""),
    }


def _va_compliance(records: list[Inspection]) -> dict[str, Any]:
    rows = [_va_row(inspection) for inspection in records]
    with_violations = sum(1 for row in rows if row["violations"])
    return {
        "kind": "va",
        "expandable": False,
        "stats": [
            _stat("Inspections on record", len(rows)),
            _stat("With violations", with_violations, warn=with_violations > 0),
            _stat("Most recent", records[0].date or "-"),
        ],
        "rows": rows,
    }


def _va_row(inspection: Inspection) -> dict[str, Any]:
    state_data = inspection.state_data or {}
    violations = _truthy(state_data.get("va_violations"))
    return {
        "type": inspection.type or "Inspection visit",
        "date": inspection.date or "",
        "violations": violations,
        "complaint": _truthy(state_data.get("va_complaint_related")),
        "summary": "Violations cited" if violations else "No violations cited",
    }


def _generic_compliance(records: list[Inspection]) -> dict[str, Any]:
    rows = [
        {
            "type": inspection.type or "Inspection",
            "date": inspection.date or "",
            "summary": inspection.original_status or "",
        }
        for inspection in records
    ]
    return {
        "kind": "generic",
        "expandable": False,
        "stats": [_stat("Inspections on record", len(rows))],
        "rows": rows,
    }


# ---------------------------------------------------------------------------
# Overview / details building blocks
# ---------------------------------------------------------------------------
_AGE_GROUPS = (
    ("infant", "Infants", "bi-emoji-smile"),
    ("toddler", "Toddlers", "bi-emoji-laughing"),
    ("preschool", "Preschool", "bi-mortarboard"),
    ("school", "School-age", "bi-backpack"),
)


def age_groups(provider: Provider) -> list[dict[str, Any]]:
    """Infant/toddler/preschool/school capacity chips, or ``[]`` if none set.

    The age columns are per-group capacity counts; a group "serves" the age when
    its count parses to > 0. Returns nothing when the state leaves them blank.
    """
    groups = []
    any_data = False
    for field, label, icon in _AGE_GROUPS:
        raw = getattr(provider, field, None)
        if _present(raw):
            any_data = True
        count = _to_int(raw)
        groups.append(
            {
                "label": label,
                "icon": icon,
                "served": count is not None and count > 0,
                "capacity": count,
            },
        )
    return groups if any_data else []


def at_a_glance(provider: Provider) -> list[dict[str, str]]:
    """The "at a glance" stat cards that actually have data."""
    candidates = (
        ("bi-grid-3x3-gap-fill", "Ages served", provider.ages_served, ""),
        ("bi-clock-fill", "Hours", provider.hours, ""),
        ("bi-house-fill", "Capacity", provider.capacity, "Licensed maximum"),
        (
            "bi-geo-alt-fill",
            "County",
            f"{provider.county} County" if provider.county else "",
            "",
        ),
    )
    return [
        {"icon": icon, "label": label, "value": str(value), "sub": sub}
        for icon, label, value, sub in candidates
        if _present(value)
    ]


def program_features(provider: Provider) -> list[dict[str, str]]:
    """Feature chips derived from real fields (languages, funding, programs)."""
    features: list[dict[str, str]] = []
    languages = provider.languages
    if isinstance(languages, list) and languages:
        label = ", ".join(str(item) for item in languages)
        features.append({"icon": "bi-translate", "label": label})
    elif isinstance(languages, str) and languages.strip():
        features.append({"icon": "bi-translate", "label": languages.strip()})

    if _truthy(provider.scholarships_accepted):
        features.append(
            {"icon": "bi-cash-coin", "label": "Publicly funded care accepted"},
        )

    state_data = provider.state_data or {}
    if _truthy(state_data.get("va_current_subsidy_provider")):
        features.append(
            {"icon": "bi-cash-coin", "label": "Child care subsidy accepted"},
        )
    features.extend(
        {"icon": "bi-patch-check-fill", "label": str(program)}
        for program in state_data.get("sc_program_participation") or []
    )
    license_type = state_data.get("va_license_type")
    if license_type:
        features.append(
            {"icon": "bi-file-earmark-text", "label": f"{license_type} license"},
        )
    return features


# Curated common columns for the Details tab (label, model field name).
_COMMON_FACT_FIELDS = (
    ("License type", "provider_type"),
    ("License number", "license_number"),
    ("License holder", "license_holder"),
    ("Administrator", "administrator"),
    ("Licensed capacity", "capacity"),
    ("Hours", "hours"),
    ("Ages served", "ages_served"),
    ("County", "county"),
    ("License issued", "license_begin_date"),
    ("License expires", "license_expiration"),
    ("Publicly funded care", "scholarships_accepted"),
)


def program_facts(provider: Provider) -> list[dict[str, str]]:
    """The full Details grid: populated common columns + humanized state_data.

    Skips empty fields (so we never show blank rows) and complex state_data
    values (lists/dicts like rating history are surfaced in their own sections).
    """
    facts: list[dict[str, str]] = []
    for label, field in _COMMON_FACT_FIELDS:
        value = getattr(provider, field, None)
        if _present(value):
            facts.append({"label": label, "value": _format_value(value)})

    languages = provider.languages
    if isinstance(languages, list) and languages:
        facts.append({"label": "Languages", "value": _format_value(languages)})

    for key, value in (provider.state_data or {}).items():
        if not _present(value) or isinstance(value, (dict, list)):
            continue
        facts.append({"label": humanize_state_key(key), "value": _format_value(value)})
    return facts


def contact_rows(provider: Provider) -> list[dict[str, str]]:
    """Phone / email / website rows for the sidebar (present only)."""
    rows: list[dict[str, str]] = []
    if provider.phone:
        rows.append(
            {
                "icon": "bi-telephone-fill",
                "value": provider.phone,
                "href": f"tel:{provider.phone}",
            },
        )
    if provider.email:
        rows.append(
            {
                "icon": "bi-envelope-fill",
                "value": provider.email,
                "href": f"mailto:{provider.email}",
            },
        )
    website = provider.provider_website
    if website:
        href = website if website.startswith("http") else f"https://{website}"
        rows.append({"icon": "bi-globe", "value": website, "href": href})
    return rows


def license_rows(provider: Provider) -> list[dict[str, str]]:
    """License-snapshot rows for the sidebar (present only)."""
    county = f"{provider.county} County" if provider.county else ""
    candidates = (
        ("License #", provider.license_number),
        ("Status", provider.status),
        ("Issued", provider.status_date or provider.license_begin_date),
        ("Expires", provider.license_expiration),
        ("County", county),
    )
    return [
        {"label": label, "value": str(value)}
        for label, value in candidates
        if _present(value)
    ]
