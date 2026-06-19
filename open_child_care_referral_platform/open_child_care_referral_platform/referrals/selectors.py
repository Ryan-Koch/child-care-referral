"""Family-scoped query helpers — the single source of truth for "what does this
family own", shared by the referrals views and the ``family_save_control`` tag
(so neither imports the other).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from open_child_care_referral_platform.referrals.models import Child
from open_child_care_referral_platform.referrals.models import Referral
from open_child_care_referral_platform.referrals.models import ReferralProvider

if TYPE_CHECKING:
    from django.db.models import QuerySet


def family_children(user) -> QuerySet[Child]:
    """Children owned by ``user``. Ordered so the per-result child picker has a
    stable default option (and "Saved for …" lists read consistently)."""
    return Child.objects.filter(family=user).order_by("first_name", "last_name", "pk")


def family_referrals(user) -> QuerySet[Referral]:
    """Referrals for ``user``'s children."""
    return Referral.objects.filter(child__family=user)


def family_saved_child_ids(user, provider) -> set[int]:
    """Ids of ``user``'s children that already have ``provider`` saved.

    The single-provider fallback for the save control; the search view batches
    the equivalent for a whole page into ``family_saved_map``.
    """
    return set(
        ReferralProvider.objects.filter(
            referral__child__family=user,
            provider=provider,
        ).values_list("referral__child_id", flat=True),
    )


def default_selected_child_id(child_param: str, children: list[Child]) -> int | None:
    """Which child the picker defaults to: the requested ``?child=`` one when it
    belongs to this family, else the first child (stable via ``family_children``'s
    ordering). Tolerates non-numeric input (returns the first child)."""
    if not children:
        return None
    try:
        chosen = int(child_param)
    except (TypeError, ValueError):
        chosen = None
    if chosen in {child.pk for child in children}:
        return chosen
    return children[0].pk
