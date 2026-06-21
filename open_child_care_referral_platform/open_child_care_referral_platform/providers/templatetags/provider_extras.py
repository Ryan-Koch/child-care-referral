from django import template

from open_child_care_referral_platform.providers.status import status_bucket

register = template.Library()


@register.filter
def is_mapping(value: object) -> bool:
    """True for dict-like JSON values (rendered as key/value rows)."""
    return isinstance(value, dict)


@register.filter
def is_sequence(value: object) -> bool:
    """True for list/tuple JSON values (rendered as bullet lists)."""
    return isinstance(value, (list, tuple))


@register.filter
def status_pill_class(status: object) -> str:
    """Compass status-pill modifier class for a provider's raw status text."""
    text = status if isinstance(status, str) else ""
    return f"compass-pill--{status_bucket(text)}"


@register.filter
def provider_rating(provider: object) -> str:
    """The provider's quality rating, taken from whichever field its state uses.

    States store the rating in different places — the cross-state ``sutq_rating``
    column, or ``state_data`` keys for SC's ABC grade / VA's quality level — so
    return the first one present (or ``""``). Done in Python rather than a
    template ``default`` chain because a missing ``state_data`` key raises when
    used as a filter argument.
    """
    direct = getattr(provider, "sutq_rating", None)
    if direct:
        return str(direct)
    state_data = getattr(provider, "state_data", None)
    if isinstance(state_data, dict):
        for key in ("sc_abc_quality_rating", "va_quality_rating"):
            value = state_data.get(key)
            if value:
                return str(value)
    return ""


@register.filter
def positive(value: object) -> bool:
    """True when scraped numeric text parses to an integer greater than zero.

    Used to mark the infant/toddler/preschool/school age chips as served vs.
    greyed; tolerates thousands separators ("1,100") and blank/non-numeric text.
    """
    try:
        return int(str(value).replace(",", "").strip()) > 0
    except (TypeError, ValueError):
        return False
