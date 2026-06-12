from __future__ import annotations

import re
from http import HTTPStatus
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import pytest
from allauth.account.models import EmailAddress
from django.contrib.auth.models import Group
from django.core import mail
from django.test import RequestFactory
from django.urls import reverse

from open_child_care_referral_platform.users.adapters import AccountAdapter
from open_child_care_referral_platform.users.claims import send_account_claim_email
from open_child_care_referral_platform.users.roles import COORDINATOR_GROUP
from open_child_care_referral_platform.users.roles import FAMILY_GROUP
from open_child_care_referral_platform.users.roles import ensure_roles
from open_child_care_referral_platform.users.tests.factories import UserFactory

if TYPE_CHECKING:
    from open_child_care_referral_platform.users.models import User

NEW_PASSWORD = "Sup3rSecr3t!Pass"  # noqa: S105  (test value, not a real secret)


def _family_user(email: str = "fam@example.com") -> User:
    ensure_roles()
    user = UserFactory.create(email=email)
    user.groups.add(Group.objects.get(name=FAMILY_GROUP))
    user.set_unusable_password()
    user.save()
    return user


@pytest.mark.django_db
def test_claim_flow_sets_password_and_verifies_email(client) -> None:
    user = _family_user()
    assert not user.has_usable_password()

    sent = send_account_claim_email(user, RequestFactory().get("/"))
    assert sent is True
    assert len(mail.outbox) == 1

    match = re.search(r"https?://\S+/password/reset/key/\S+", str(mail.outbox[0].body))
    assert match is not None
    key_path = urlparse(match.group(0)).path

    # allauth redirects the key URL to a set-password URL (key stashed in session).
    response = client.get(key_path)
    set_password_url = (
        response.url if response.status_code == HTTPStatus.FOUND else key_path
    )
    response = client.post(
        set_password_url,
        {"password1": NEW_PASSWORD, "password2": NEW_PASSWORD},
    )
    assert response.status_code == HTTPStatus.FOUND

    user.refresh_from_db()
    assert user.has_usable_password()
    assert user.check_password(NEW_PASSWORD)
    # Completing the emailed reset proves control of the inbox → email verified
    # (via the password_reset signal receiver).
    assert EmailAddress.objects.filter(user=user, verified=True).exists()

    # End to end: the family can now log in and lands on the portal.
    login_response = client.post(
        reverse("account_login"),
        {"login": user.email, "password": NEW_PASSWORD},
    )
    assert login_response.status_code == HTTPStatus.FOUND
    assert login_response.url == reverse("referrals:portal")


def _request_with_user(user: User):
    request = RequestFactory().get("/")
    request.user = user
    return request


@pytest.mark.django_db
def test_login_redirect_coordinator_to_queue() -> None:
    ensure_roles()
    user = UserFactory.create()
    user.groups.add(Group.objects.get(name=COORDINATOR_GROUP))
    url = AccountAdapter().get_login_redirect_url(_request_with_user(user))
    assert url == reverse("referrals:queue")


@pytest.mark.django_db
def test_login_redirect_family_to_portal() -> None:
    url = AccountAdapter().get_login_redirect_url(_request_with_user(_family_user()))
    assert url == reverse("referrals:portal")


@pytest.mark.django_db
def test_login_redirect_other_user_falls_back() -> None:
    ensure_roles()
    user = UserFactory.create()
    url = AccountAdapter().get_login_redirect_url(_request_with_user(user))
    assert url != reverse("referrals:queue")
    assert url != reverse("referrals:portal")
