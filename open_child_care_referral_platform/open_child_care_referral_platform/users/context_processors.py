from django.conf import settings

from open_child_care_referral_platform.users.roles import COORDINATOR_GROUP
from open_child_care_referral_platform.users.roles import FAMILY_GROUP


def allauth_settings(request):
    """Expose some settings from django-allauth in templates."""
    return {
        "ACCOUNT_ALLOW_REGISTRATION": settings.ACCOUNT_ALLOW_REGISTRATION,
    }


def user_roles(request):
    """Expose the current user's role-group membership to every template.

    Used to show/hide role-specific navigation (e.g. the coordinator referral
    queue). Superusers count as coordinators, matching ``CoordinatorRequiredMixin``.
    """
    user = request.user
    if not user.is_authenticated:
        return {"is_coordinator": False, "is_family": False}
    group_names = set(user.groups.values_list("name", flat=True))
    return {
        "is_coordinator": user.is_superuser or COORDINATOR_GROUP in group_names,
        "is_family": FAMILY_GROUP in group_names,
    }
