from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any

from django import template

from open_child_care_referral_platform.referrals.models import Child
from open_child_care_referral_platform.referrals.models import ReferralProvider

if TYPE_CHECKING:
    from django.http import HttpRequest
    from django.template.context import Context

    from open_child_care_referral_platform.providers.models import Provider

register = template.Library()


@register.inclusion_tag("referrals/_family_save_control.html", takes_context=True)
def family_save_control(context: Context, provider: Provider) -> dict[str, Any]:
    """Render a "save this provider for one of my children" control.

    Shared by the family provider search (Task 12) and the provider detail page
    (Task 13) so neither template hardcodes the form. Renders nothing for
    non-family users, an "add a child" prompt for a family with no children, and
    a child ``<select>`` + Save form otherwise.

    ``family_children`` / ``family_saved_map`` are read from the page context
    when the view precomputed them (the search view does, to stay one query per
    page); otherwise they're computed here for the single ``provider`` (the
    detail page, which doesn't know about referrals).
    """
    if not context.get("is_family"):
        return {"is_family": False}
    request = context["request"]
    user = request.user

    children = context.get("family_children")
    if children is None:
        children = list(Child.objects.filter(family=user))

    saved_map = context.get("family_saved_map")
    if saved_map is None:
        saved_child_ids = set(
            ReferralProvider.objects.filter(
                referral__child__family=user,
                provider=provider,
            ).values_list("referral__child_id", flat=True),
        )
    else:
        saved_child_ids = saved_map.get(provider.pk, set())

    saved_names = [str(c) for c in children if c.pk in saved_child_ids]
    return {
        "is_family": True,
        "provider": provider,
        "children": children,
        # Pre-joined so the template needs no comma-juggling loop (keeps the
        # rendered list as "Alice, Bob" without stray whitespace).
        "saved_children_label": ", ".join(saved_names),
        "selected_child_id": _selected_child_id(request, children),
        "next_url": request.get_full_path(),
    }


def _selected_child_id(request: HttpRequest, children: list[Child]) -> int | None:
    """The child the dropdown defaults to: the ``?child=`` one when it belongs to
    this family, else the first child (so a save is never mis-targeted)."""
    if not children:
        return None
    raw = request.GET.get("child", "")
    child_ids = {child.pk for child in children}
    if raw.isdigit() and int(raw) in child_ids:
        return int(raw)
    return children[0].pk
