from __future__ import annotations

import pytest
from django.db import IntegrityError
from django.db import transaction

from open_child_care_referral_platform.providers.models import Provider
from open_child_care_referral_platform.providers.tests.factories import ProviderFactory
from open_child_care_referral_platform.referrals.models import Child
from open_child_care_referral_platform.referrals.models import Referral
from open_child_care_referral_platform.referrals.models import ReferralProvider
from open_child_care_referral_platform.referrals.tests.factories import ChildFactory
from open_child_care_referral_platform.referrals.tests.factories import ReferralFactory
from open_child_care_referral_platform.referrals.tests.factories import SchoolFactory


@pytest.mark.django_db
def test_child_factory_creates_child_with_defaults() -> None:
    child = ChildFactory.create()
    assert child.pk is not None
    assert child.family.pk is not None
    assert child.relationship == Child.Relationship.CHILD
    assert child.referral_need == Child.ReferralNeed.NEED_ASSISTANCE
    assert child.in_school is False
    assert child.care_schedule == {}
    assert child.active_provider is None


@pytest.mark.django_db
def test_child_str_uses_name_then_falls_back() -> None:
    named = ChildFactory.create(first_name="Sam", last_name="Rivera")
    assert str(named) == "Sam Rivera"
    blank = ChildFactory.create(first_name="", last_name="")
    assert str(blank) == f"Child #{blank.pk}"


@pytest.mark.django_db
def test_care_schedule_round_trips() -> None:
    schedule = {
        "monday": [["07:30", "09:00"], ["15:30", "18:00"]],
        "friday": [["07:30", "09:00"]],
    }
    child = ChildFactory.create(care_schedule=schedule)
    child.refresh_from_db()
    assert child.care_schedule == schedule


@pytest.mark.django_db
def test_active_provider_is_nullable_and_settable() -> None:
    child = ChildFactory.create()
    provider = Provider.objects.create(provider_name="Bright Beginnings")
    child.active_provider = provider
    child.save()
    child.refresh_from_db()
    assert child.active_provider == provider


@pytest.mark.django_db
def test_school_belongs_to_child() -> None:
    school = SchoolFactory.create(institution_name="Lincoln Elementary")
    assert str(school) == "Lincoln Elementary"
    assert list(school.child.schools.all()) == [school]


@pytest.mark.django_db
def test_referral_defaults() -> None:
    referral = ReferralFactory.create()
    assert referral.status == Referral.Status.NEW
    assert referral.source == Referral.Source.STAFF
    assert referral.help_requested is False
    assert referral.external_id == ""
    assert referral.coordinator is None


@pytest.mark.django_db
def test_saved_provider_through_model_is_idempotent() -> None:
    referral = ReferralFactory.create()
    provider = ProviderFactory.create()
    link, created = ReferralProvider.objects.get_or_create(
        referral=referral,
        provider=provider,
    )
    assert created is True
    assert list(referral.providers.all()) == [provider]
    assert list(referral.saved_providers.all()) == [link]

    _, created_again = ReferralProvider.objects.get_or_create(
        referral=referral,
        provider=provider,
    )
    assert created_again is False


@pytest.mark.django_db
def test_provider_unique_per_referral() -> None:
    referral = ReferralFactory.create()
    provider = ProviderFactory.create()
    ReferralProvider.objects.create(referral=referral, provider=provider)
    with pytest.raises(IntegrityError), transaction.atomic():
        ReferralProvider.objects.create(referral=referral, provider=provider)


@pytest.mark.django_db
def test_external_id_blank_repeatable_but_nonblank_unique() -> None:
    child = ChildFactory.create()
    # Many blanks coexist (the conditional unique constraint excludes "").
    Referral.objects.create(child=child, external_id="")
    Referral.objects.create(child=child, external_id="")
    # A non-blank value is unique.
    Referral.objects.create(child=child, external_id="req-1")
    with pytest.raises(IntegrityError), transaction.atomic():
        Referral.objects.create(child=child, external_id="req-1")
