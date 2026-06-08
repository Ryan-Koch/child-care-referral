from django import template

register = template.Library()


@register.filter
def is_mapping(value: object) -> bool:
    """True for dict-like JSON values (rendered as key/value rows)."""
    return isinstance(value, dict)


@register.filter
def is_sequence(value: object) -> bool:
    """True for list/tuple JSON values (rendered as bullet lists)."""
    return isinstance(value, (list, tuple))
