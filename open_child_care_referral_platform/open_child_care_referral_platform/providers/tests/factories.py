from __future__ import annotations

from factory import Faker
from factory.django import DjangoModelFactory

from open_child_care_referral_platform.providers.models import Provider


class ProviderFactory(DjangoModelFactory[Provider]):
    provider_name = Faker("company")
    source_state = "OH"

    class Meta:
        model = Provider
