from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest
from django.contrib.auth.models import Group
from django.urls import reverse

from open_child_care_referral_platform.referrals.models import Referral
from open_child_care_referral_platform.referrals.tests.factories import ReferralFactory
from open_child_care_referral_platform.users.roles import COORDINATOR_GROUP
from open_child_care_referral_platform.users.roles import FAMILY_GROUP
from open_child_care_referral_platform.users.roles import ensure_roles
from open_child_care_referral_platform.users.tests.factories import UserFactory

if TYPE_CHECKING:
    from open_child_care_referral_platform.users.models import User


def make_coordinator() -> User:
    ensure_roles()
    user = UserFactory.create()
    user.groups.add(Group.objects.get(name=COORDINATOR_GROUP))
    return user


def make_family() -> User:
    ensure_roles()
    user = UserFactory.create()
    user.groups.add(Group.objects.get(name=FAMILY_GROUP))
    return user


@pytest.mark.django_db
def test_queue_redirects_anonymous_to_login(client) -> None:
    response = client.get(reverse("referrals:queue"))
    assert response.status_code == HTTPStatus.FOUND


@pytest.mark.django_db
def test_queue_forbids_non_coordinator(client) -> None:
    client.force_login(make_family())
    response = client.get(reverse("referrals:queue"))
    assert response.status_code == HTTPStatus.FORBIDDEN


@pytest.mark.django_db
def test_queue_allows_coordinator(client) -> None:
    client.force_login(make_coordinator())
    response = client.get(reverse("referrals:queue"))
    assert response.status_code == HTTPStatus.OK


@pytest.mark.django_db
def test_queue_defaults_to_active_oldest_first(client) -> None:
    client.force_login(make_coordinator())
    older = ReferralFactory.create(status=Referral.Status.NEW)
    newer = ReferralFactory.create(status=Referral.Status.IN_PROGRESS)
    completed = ReferralFactory.create(status=Referral.Status.COMPLETED)

    response = client.get(reverse("referrals:queue"))
    referrals = list(response.context["referrals"])

    assert completed not in referrals
    assert referrals.index(older) < referrals.index(newer)


@pytest.mark.django_db
def test_queue_status_filter_can_surface_completed(client) -> None:
    client.force_login(make_coordinator())
    active = ReferralFactory.create(status=Referral.Status.NEW)
    completed = ReferralFactory.create(status=Referral.Status.COMPLETED)

    response = client.get(
        reverse("referrals:queue"),
        {"status": Referral.Status.COMPLETED},
    )
    referrals = list(response.context["referrals"])

    assert completed in referrals
    assert active not in referrals


@pytest.mark.django_db
def test_queue_mine_filter(client) -> None:
    coordinator = make_coordinator()
    other = make_coordinator()
    client.force_login(coordinator)
    mine = ReferralFactory.create(
        status=Referral.Status.ASSIGNED,
        coordinator=coordinator,
    )
    theirs = ReferralFactory.create(
        status=Referral.Status.ASSIGNED,
        coordinator=other,
    )

    response = client.get(reverse("referrals:queue"), {"mine": "1"})
    referrals = list(response.context["referrals"])

    assert mine in referrals
    assert theirs not in referrals


@pytest.mark.django_db
def test_queue_help_filter(client) -> None:
    client.force_login(make_coordinator())
    needs_help = ReferralFactory.create(
        status=Referral.Status.NEW,
        help_requested=True,
    )
    normal = ReferralFactory.create(status=Referral.Status.NEW)

    response = client.get(reverse("referrals:queue"), {"help": "1"})
    referrals = list(response.context["referrals"])

    assert needs_help in referrals
    assert normal not in referrals
