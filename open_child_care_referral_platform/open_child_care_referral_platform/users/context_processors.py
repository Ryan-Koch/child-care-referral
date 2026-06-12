from django.conf import settings
from django.db.models import Q

from open_child_care_referral_platform.referrals.models import Message
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


def unread_messages(request):
    """Expose the current user's unread-message count for the nav badge (Task 10).

    For a family this is the number of messages the coordinator side has sent on
    their referrals that they haven't read yet (a message on their own referral
    not sent by them). For non-family authenticated users the filter matches
    nothing, so this stays a single cheap query and a zero badge.
    """
    user = request.user
    if not user.is_authenticated:
        return {"unread_message_count": 0}
    count = (
        Message.objects.filter(
            referral__child__family=user,
            read_at__isnull=True,
        )
        .filter(~Q(sender=user))
        .count()
    )
    return {"unread_message_count": count}
