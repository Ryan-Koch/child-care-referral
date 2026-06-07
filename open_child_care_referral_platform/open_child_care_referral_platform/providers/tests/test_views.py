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
