from __future__ import annotations

from factory import Faker
from factory import SubFactory
from factory.django import DjangoModelFactory

from open_child_care_referral_platform.providers.tests.factories import ProviderFactory
from open_child_care_referral_platform.referrals.models import Child
from open_child_care_referral_platform.referrals.models import Referral
from open_child_care_referral_platform.referrals.models import ReferralProvider
from open_child_care_referral_platform.referrals.models import School
from open_child_care_referral_platform.users.tests.factories import UserFactory


class ChildFactory(DjangoModelFactory[Child]):
    family = SubFactory(UserFactory)
    first_name = Faker("first_name")
    last_name = Faker("last_name")
    date_of_birth = Faker("date_of_birth", minimum_age=0, maximum_age=12)

    class Meta:
        model = Child


class SchoolFactory(DjangoModelFactory[School]):
    child = SubFactory(ChildFactory)
    institution_name = Faker("company")
    city = Faker("city")
    state = Faker("state_abbr")

    class Meta:
        model = School


class ReferralFactory(DjangoModelFactory[Referral]):
    child = SubFactory(ChildFactory)

    class Meta:
        model = Referral


class ReferralProviderFactory(DjangoModelFactory[ReferralProvider]):
    referral = SubFactory(ReferralFactory)
    provider = SubFactory(ProviderFactory)

    class Meta:
        model = ReferralProvider
