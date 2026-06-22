from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any

from django import template
from django.utils import timezone

from open_child_care_referral_platform.referrals.models import Referral
from open_child_care_referral_platform.referrals.models import ReferralProvider
from open_child_care_referral_platform.referrals.selectors import (
    default_selected_child_id,
)
from open_child_care_referral_platform.referrals.selectors import family_children
from open_child_care_referral_platform.referrals.selectors import family_saved_child_ids

if TYPE_CHECKING:
    from datetime import date as date_type

    from django.template.context import Context

    from open_child_care_referral_platform.providers.models import Provider
    from open_child_care_referral_platform.referrals.models import Child

register = template.Library()


@register.inclusion_tag("referrals/_family_save_control.html", takes_context=True)
def family_save_control(context: Context, provider: Provider) -> dict[str, Any]:
    """Render a "save this provider for one of my children" control.

    Shared by the family provider search (Task 12) and the provider detail page
    (Task 13). Renders nothing for non-family users, an "add a child" prompt for
    a family with no children, and a child ``<select>`` + Save form otherwise.

    The search view precomputes ``family_children`` / ``family_saved_map`` /
    ``family_selected_child_id`` / ``family_save_next`` so a multi-card page stays
    one query and computes the picker state once; on the detail page (no such
    context) each value falls back to a single-provider lookup via the shared
    ``referrals.selectors`` helpers, so both paths agree.
    """
    if not context.get("is_family"):
        return {"is_family": False}
    request = context["request"]
    user = request.user

    children = context.get("family_children")
    if children is None:
        children = list(family_children(user))

    saved_map = context.get("family_saved_map")
    if saved_map is None:
        saved_child_ids = family_saved_child_ids(user, provider)
    else:
        saved_child_ids = saved_map.get(provider.pk, set())

    selected_child_id = context.get("family_selected_child_id")
    if selected_child_id is None:
        selected_child_id = default_selected_child_id(
            request.GET.get("child", ""),
            children,
        )

    return {
        "is_family": True,
        "provider": provider,
        "children": children,
        "saved_children_label": ", ".join(
            str(child) for child in children if child.pk in saved_child_ids
        ),
        "selected_child_id": selected_child_id,
        "next_url": context.get("family_save_next") or request.get_full_path(),
    }


# --- coordinator referral queue (Task 04 / "Referral Queue" design) --------
#
# The queue's row view-model. Mirrors the source design's per-row computation,
# but every value is derived from the real ``Referral``/``Child``/``User`` rows
# (the view ``select_related``s child, family and coordinator, so reading them
# here adds no queries).

# Statuses that count as live, actionable work (matches views.ACTIVE_STATUSES).
_ACTIVE_STATUSES = frozenset(
    {Referral.Status.NEW, Referral.Status.ASSIGNED, Referral.Status.IN_PROGRESS},
)
# A referral waiting at least this many days is flagged urgent in the queue.
_URGENT_DAYS = 10
# Deterministic avatar palette; keep in sync with .rq-avatar--N in compass_queue.css.
_AVATAR_PALETTE_COUNT = 4
# Age bands as (exclusive upper bound in years, label, Bootstrap icon).
_AGE_BANDS: tuple[tuple[int, str, str], ...] = (
    (1, "Infant", "bi bi-emoji-smile"),
    (3, "Toddler", "bi bi-emoji-laughing"),
    (5, "Preschool", "bi bi-mortarboard"),
)
_SCHOOL_AGE = ("School-age", "bi bi-backpack")


def _age_band(date_of_birth: date_type | None) -> tuple[str, str]:
    """Map a child's date of birth to a (label, icon) care band."""
    if date_of_birth is None:
        return ("Age not on file", "bi bi-question-circle")
    today = timezone.localdate()
    years = (
        today.year
        - date_of_birth.year
        - ((today.month, today.day) < (date_of_birth.month, date_of_birth.day))
    )
    for ceiling, label, icon in _AGE_BANDS:
        if years < ceiling:
            return (label, icon)
    return _SCHOOL_AGE


def _initials(name: str) -> str:
    """Up to two uppercase initials from a name, for the assignee avatar."""
    parts = [part for part in name.split() if part]
    return "".join(part[0] for part in parts[:2]).upper() or "?"


@register.filter
def initials(value: str) -> str:
    """Up to two uppercase initials from a name (or email), for avatars.

    Exposed for the referral detail page's assignee and family-contact avatars;
    shares the queue's ``_initials`` so the two stay in sync.
    """
    return _initials(value or "")


def _avatar_index(name: str) -> int:
    """Stable 0..N-1 palette slot for a name (same hash as the source design)."""
    total = 0
    for char in name:
        total = (total * 31 + ord(char)) % _AVATAR_PALETTE_COUNT
    return total


@register.filter
def queue_row(referral: Referral) -> dict[str, Any]:
    """Display fields for one referral queue row.

    Bundled into a single filter (rather than several) so the template stays a
    straight render of a row "view-model", the way the source design computed it.
    """
    child = referral.child
    family = child.family
    coordinator = referral.coordinator
    age_label, age_icon = _age_band(child.date_of_birth)
    is_active = referral.status in _ACTIVE_STATUSES
    waiting_days = (timezone.now() - referral.created).days
    assignee = ""
    if coordinator is not None:
        assignee = coordinator.name or coordinator.email
    return {
        "child": str(child),
        "family": family.name or "—",
        "email": family.email,
        "needs_help": referral.help_requested,
        "age_label": age_label,
        "age_icon": age_icon,
        "care_detail": child.get_referral_need_display(),
        "status_label": referral.get_status_display(),
        "status_class": f"rq-status--{referral.status}",
        "assigned": coordinator is not None,
        "assignee": assignee,
        "initials": _initials(assignee) if assignee else "",
        "avatar_class": f"rq-avatar--{_avatar_index(assignee)}" if assignee else "",
        "waiting_label": (
            f"{waiting_days} day{'' if waiting_days == 1 else 's'}"
            if is_active
            else "—"
        ),
        "urgent": is_active and waiting_days >= _URGENT_DAYS,
        "source_label": referral.get_source_display(),
    }


# --- family portal home ("Family Portal" design) ---------------------------
#
# The family "My children" card view-model. Like ``queue_row``, this bundles a
# child's display into one structure so the template stays a straight render of
# the design's nested children -> referrals -> saved-providers layout. Every
# value derives from the real Child / Referral / ReferralProvider rows the view
# prefetches (referrals with an ``unread_coordinator_messages`` annotation, and
# ``saved_providers__provider``), so reading them here adds no queries.

# Referral status -> (pill label, pill modifier suffix). Shared by the child
# summary pill and the per-referral header pill.
_REFERRAL_STATUS_PILL: dict[str, tuple[str, str]] = {
    Referral.Status.NEW: ("Getting started", "new"),
    Referral.Status.ASSIGNED: ("In progress", "assigned"),
    Referral.Status.IN_PROGRESS: ("In progress", "in_progress"),
    Referral.Status.COMPLETED: ("Matched", "completed"),
    Referral.Status.CLOSED: ("Closed", "closed"),
}
# Saved-provider status -> (pill label, pill modifier suffix).
_PROVIDER_STAGE_PILL: dict[str, tuple[str, str]] = {
    ReferralProvider.Status.SUGGESTED: ("Suggested", "suggested"),
    ReferralProvider.Status.SHARED: ("Shared with you", "shared"),
    ReferralProvider.Status.SELECTED: ("Your pick", "selected"),
    ReferralProvider.Status.DECLINED: ("Passed", "declined"),
}
# Display order for saved providers: things to act on first, passed last.
_PROVIDER_STAGE_RANK: dict[str, int] = {
    ReferralProvider.Status.SHARED: 0,
    ReferralProvider.Status.SELECTED: 1,
    ReferralProvider.Status.SUGGESTED: 2,
    ReferralProvider.Status.DECLINED: 3,
}
# Statuses a family may still respond to ("I'm interested" / "Not for us").
_RESPONDABLE_STAGES = frozenset(
    {ReferralProvider.Status.SUGGESTED, ReferralProvider.Status.SHARED},
)
# Referral statuses that count as a live search (mirrors views.ACTIVE_STATUSES).
_FAMILY_ACTIVE_STATUSES = frozenset(
    {Referral.Status.NEW, Referral.Status.ASSIGNED, Referral.Status.IN_PROGRESS},
)
_MONTHS_PER_YEAR = 12


def _age_detail(date_of_birth: date_type | None) -> str:
    """A human age string ("5 months old" / "3 years old"), or "" if unknown."""
    if date_of_birth is None:
        return ""
    today = timezone.localdate()
    months = (today.year - date_of_birth.year) * _MONTHS_PER_YEAR + (
        today.month - date_of_birth.month
    )
    if today.day < date_of_birth.day:
        months -= 1
    months = max(months, 0)
    years = months // _MONTHS_PER_YEAR
    if years < 1:
        return f"{months} month{'' if months == 1 else 's'} old"
    return f"{years} year{'' if years == 1 else 's'} old"


def _reason_from_band(age_label: str) -> str:
    """A friendly referral reason from the child's age band ("Infant care")."""
    if age_label == "Age not on file":
        return "Child care"
    return f"{age_label} care"


def _referral_sort_key(referral: Referral) -> tuple[int, float]:
    """Active referrals first, then most-recently opened."""
    active = referral.status in _FAMILY_ACTIVE_STATUSES
    return (0 if active else 1, -referral.created.timestamp())


def _provider_vm(saved: ReferralProvider, *, referral_active: bool) -> dict[str, Any]:
    label, modifier = _PROVIDER_STAGE_PILL.get(
        saved.status,
        _PROVIDER_STAGE_PILL[ReferralProvider.Status.SUGGESTED],
    )
    provider = saved.provider
    return {
        "saved_pk": saved.pk,
        "provider_pk": provider.pk,
        "name": str(provider),
        "loc": (provider.address or "").strip(),
        "county": (provider.county or "").strip(),
        "stage_label": label,
        "stage_class": f"fp-pill--{modifier}",
        "note": saved.notes.strip(),
        "passed": saved.status == ReferralProvider.Status.DECLINED,
        "can_respond": referral_active and saved.status in _RESPONDABLE_STAGES,
    }


@register.filter
def family_child_card(child: Child) -> dict[str, Any]:
    """Display fields for one child's card on the family portal home."""
    referrals = sorted(child.referrals.all(), key=_referral_sort_key)
    age_label, age_icon = _age_band(child.date_of_birth)
    multi = len(referrals) > 1
    total_providers = 0
    pending = 0

    referral_vms: list[dict[str, Any]] = []
    for index, referral in enumerate(referrals):
        active = referral.status in _FAMILY_ACTIVE_STATUSES
        saved = sorted(
            referral.saved_providers.all(),
            key=lambda item: _PROVIDER_STAGE_RANK.get(item.status, 9),
        )
        total_providers += len(saved)
        if active:
            pending += sum(
                1 for item in saved if item.status == ReferralProvider.Status.SHARED
            )
        status_label, status_modifier = _REFERRAL_STATUS_PILL.get(
            referral.status,
            _REFERRAL_STATUS_PILL[Referral.Status.NEW],
        )
        referral_vms.append(
            {
                "pk": referral.pk,
                "show_header": multi,
                "first": index == 0,
                "reason": _reason_from_band(age_label),
                "date_label": f"Opened {referral.created:%b %-d, %Y}",
                "status_label": status_label,
                "status_class": f"fp-pill--{status_modifier}",
                "active": active,
                "help_requested": referral.help_requested,
                "unread": getattr(referral, "unread_coordinator_messages", 0),
                "empty_note": multi and not saved,
                "providers": [
                    _provider_vm(item, referral_active=active) for item in saved
                ],
            },
        )

    # The child's summary pill follows its primary (first, active-first) referral.
    primary_status = referrals[0].status if referrals else Referral.Status.NEW
    child_label, child_modifier = _REFERRAL_STATUS_PILL.get(
        primary_status,
        _REFERRAL_STATUS_PILL[Referral.Status.NEW],
    )
    return {
        "pk": child.pk,
        "name": str(child),
        "icon": age_icon,
        "status_label": child_label,
        "status_class": f"fp-pill--{child_modifier}",
        "age_label": age_label,
        "age_detail": _age_detail(child.date_of_birth),
        "need_label": child.get_referral_need_display(),
        "help": any(referral.help_requested for referral in referrals),
        "multi": multi,
        "ref_count": len(referrals),
        "pending": pending,
        "pending_word": "provider is" if pending == 1 else "providers are",
        "empty": not multi and total_providers == 0,
        "referrals": referral_vms,
    }
