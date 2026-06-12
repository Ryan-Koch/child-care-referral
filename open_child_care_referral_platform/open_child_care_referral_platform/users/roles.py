"""Role definitions shared across apps.

Roles are modeled as Django auth ``Group``s (see ``app_structure.md`` →
"Roles & access"): a Coordinator is a ``users.User`` in the ``Coordinator``
group; a Family is a ``User`` in the ``Family`` group. These names are the single
source of truth — import the constants rather than hardcoding the strings.
"""

from django.contrib.auth.models import Group

COORDINATOR_GROUP = "Coordinator"
FAMILY_GROUP = "Family"


def ensure_roles() -> None:
    """Idempotently create the role groups. Safe to call repeatedly."""
    for name in (COORDINATOR_GROUP, FAMILY_GROUP):
        Group.objects.get_or_create(name=name)
