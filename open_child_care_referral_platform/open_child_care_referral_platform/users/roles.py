"""Role definitions shared across apps.

Roles are modeled as Django auth ``Group``s (see ``app_structure.md`` →
"Roles & access"): a Coordinator is a ``users.User`` in the ``Coordinator``
group; a Family is a ``User`` in the ``Family`` group. These names are the single
source of truth — import the constants rather than hardcoding the strings.
"""

from django.contrib.auth.models import Group

COORDINATOR_GROUP = "Coordinator"
FAMILY_GROUP = "Family"


def user_in_group(user, group_name: str) -> bool:
    """True if ``user`` is authenticated and a member of ``group_name``.

    The one place role-group membership is decided; the access mixins and the
    ``user_roles`` context processor build on it. Superuser bypass (where it
    applies) is layered on by the caller, since it is role-specific.
    """
    return user.is_authenticated and user.groups.filter(name=group_name).exists()


def ensure_roles() -> None:
    """Idempotently create the role groups. Safe to call repeatedly."""
    for name in (COORDINATOR_GROUP, FAMILY_GROUP):
        Group.objects.get_or_create(name=name)
