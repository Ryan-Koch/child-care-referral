from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any

from django import template

from open_child_care_referral_platform.referrals.selectors import (
    default_selected_child_id,
)
from open_child_care_referral_platform.referrals.selectors import family_children
from open_child_care_referral_platform.referrals.selectors import family_saved_child_ids

if TYPE_CHECKING:
    from django.template.context import Context

    from open_child_care_referral_platform.providers.models import Provider

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
