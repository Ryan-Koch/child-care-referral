from http import HTTPStatus

import pytest
from django.urls import reverse

from open_child_care_referral_platform.providers.models import Inspection
from open_child_care_referral_platform.providers.models import Provider


@pytest.fixture
def provider(db):
    provider = Provider.objects.create(
        provider_name="Cheraw Head Start",
        provider_type="Child Care Center",
        license_number="716",
        source_state="South Carolina",
        address="1345A Dizzy Gillespie Drive, CHERAW, SC 29520",
        state_data={
            "sc_provider_id": "4263",
            "sc_abc_quality_rating": "A+",
            "sc_abc_rating_history": [{"date": "8/28/2024", "rating": "A+"}],
        },
    )
    Inspection.objects.create(
        provider=provider,
        type="Annual Review",
        date="6/13/2025",
        state_data={"sc_alert_count": 2},
    )
    return provider


@pytest.mark.django_db
def test_list_links_each_card_to_detail(client, provider):
    response = client.get(reverse("providers:list"))

    assert response.status_code == HTTPStatus.OK
    detail_url = reverse("providers:detail", kwargs={"pk": provider.pk})
    assert detail_url in response.content.decode()


@pytest.mark.django_db
def test_detail_renders_core_columns(client, provider):
    response = client.get(reverse("providers:detail", kwargs={"pk": provider.pk}))

    assert response.status_code == HTTPStatus.OK
    content = response.content.decode()
    assert "Cheraw Head Start" in content
    assert "716" in content
    assert provider.address in content


@pytest.mark.django_db
def test_detail_renders_nested_state_data_and_inspections(client, provider):
    response = client.get(reverse("providers:detail", kwargs={"pk": provider.pk}))

    content = response.content.decode()
    # Provider state_data keys/values (including nested rating history).
    assert "sc_provider_id" in content
    assert "4263" in content
    assert "sc_abc_rating_history" in content
    # Inspection and its own state_data are shown too.
    assert "Annual Review" in content
    assert "sc_alert_count" in content


@pytest.fixture
def two_county_providers(db):
    Provider.objects.create(
        provider_name="Richland Place",
        source_state="South Carolina",
        county="Richland",
    )
    Provider.objects.create(
        provider_name="Chesterfield Place",
        source_state="South Carolina",
        county="Chesterfield",
    )


@pytest.mark.django_db
def test_counties_populate_only_after_state_selected(client, two_county_providers):
    # No state chosen: state options exist, but counties are withheld.
    unfiltered = client.get(reverse("providers:list"))
    assert unfiltered.context["states"] == ["South Carolina"]
    assert unfiltered.context["counties"] == []

    # State chosen: its distinct counties are offered, sorted.
    filtered = client.get(reverse("providers:list"), {"state": "South Carolina"})
    assert filtered.context["counties"] == ["Chesterfield", "Richland"]


@pytest.mark.django_db
def test_county_filter_limits_results(client, two_county_providers):
    response = client.get(
        reverse("providers:list"),
        {"state": "South Carolina", "county": "Richland"},
    )

    names = [provider.provider_name for provider in response.context["providers"]]
    assert names == ["Richland Place"]


@pytest.mark.django_db
def test_county_from_another_state_is_ignored(client, two_county_providers):
    # A county that is not in the selected state must not filter anything out.
    response = client.get(
        reverse("providers:list"),
        {"state": "South Carolina", "county": "Nonexistent"},
    )

    assert response.context["paginator"].count == Provider.objects.count()
