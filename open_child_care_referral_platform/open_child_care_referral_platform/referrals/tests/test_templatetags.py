from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from open_child_care_referral_platform.referrals.models import Referral
from open_child_care_referral_platform.referrals.templatetags.referral_extras import (
    queue_row,
)
from open_child_care_referral_platform.referrals.tests.factories import ReferralFactory
from open_child_care_referral_platform.users.tests.factories import make_coordinator

_YEAR = 365


@pytest.mark.django_db
def test_queue_row_age_band_from_dob() -> None:
    today = timezone.localdate()
    infant = ReferralFactory.create(
        child__date_of_birth=today - timedelta(days=180),
    )
    school_age = ReferralFactory.create(
        child__date_of_birth=today - timedelta(days=8 * _YEAR),
    )

    assert queue_row(infant)["age_label"] == "Infant"
    assert queue_row(school_age)["age_label"] == "School-age"


@pytest.mark.django_db
def test_queue_row_handles_missing_dob() -> None:
    referral = ReferralFactory.create(child__date_of_birth=None)

    assert queue_row(referral)["age_label"] == "Age not on file"


@pytest.mark.django_db
def test_queue_row_assignee_initials_and_avatar() -> None:
    coordinator = make_coordinator()
    coordinator.name = "Dana Price"
    coordinator.save()
    assigned = ReferralFactory.create(
        status=Referral.Status.ASSIGNED,
        coordinator=coordinator,
    )

    row = queue_row(assigned)

    assert row["assigned"] is True
    assert row["assignee"] == "Dana Price"
    assert row["initials"] == "DP"
    assert row["avatar_class"].startswith("rq-avatar--")


@pytest.mark.django_db
def test_queue_row_unassigned_has_no_avatar() -> None:
    row = queue_row(ReferralFactory.create(status=Referral.Status.NEW))

    assert row["assigned"] is False
    assert row["assignee"] == ""
    assert row["initials"] == ""
    assert row["avatar_class"] == ""


@pytest.mark.django_db
def test_queue_row_waiting_only_for_active() -> None:
    active = ReferralFactory.create(status=Referral.Status.NEW)
    closed = ReferralFactory.create(status=Referral.Status.CLOSED)

    assert queue_row(active)["waiting_label"].endswith("days")
    assert queue_row(closed)["waiting_label"] == "—"
