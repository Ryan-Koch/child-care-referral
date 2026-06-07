import pytest

from open_child_care_referral_platform.providers.models import Inspection
from open_child_care_referral_platform.providers.models import Provider


@pytest.mark.django_db
def test_provider_is_creatable_with_no_fields():
    """Every field is optional: a Provider with only its PK must round-trip."""
    provider = Provider.objects.create()

    provider.refresh_from_db()
    assert provider.pk is not None
    assert provider.state_data == {}


@pytest.mark.django_db
def test_provider_state_data_holds_arbitrary_keys():
    provider = Provider.objects.create(
        provider_name="Sunshine Daycare",
        source_state="VA",
        state_data={"va_quality_rating": "3", "va_total_points": "42"},
    )

    provider.refresh_from_db()
    assert provider.state_data["va_quality_rating"] == "3"


@pytest.mark.django_db
def test_inspection_is_optional_and_linked_to_provider():
    provider = Provider.objects.create(provider_name="Sunshine Daycare")
    inspection = Inspection.objects.create(
        provider=provider,
        type="Routine",
        state_data={"va_violations": ["A1", "B2"]},
    )

    inspection.refresh_from_db()
    assert inspection.pk is not None
    assert inspection.state_data == {"va_violations": ["A1", "B2"]}
    assert list(provider.inspections.all()) == [inspection]
