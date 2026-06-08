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


@pytest.fixture
def typed_providers(db):
    Provider.objects.create(
        provider_name="Center A",
        source_state="South Carolina",
        provider_type="Child Care Center",
    )
    Provider.objects.create(
        provider_name="Home B",
        source_state="South Carolina",
        provider_type="Family Child Care Home",
    )
    Provider.objects.create(
        provider_name="Exempt C",
        source_state="South Carolina",
        provider_type="Exempt Child Care Center",
    )


@pytest.mark.django_db
def test_provider_types_populate_only_after_state_selected(client, typed_providers):
    unfiltered = client.get(reverse("providers:list"))
    assert unfiltered.context["provider_types"] == []

    filtered = client.get(reverse("providers:list"), {"state": "South Carolina"})
    assert filtered.context["provider_types"] == [
        "Child Care Center",
        "Exempt Child Care Center",
        "Family Child Care Home",
    ]


@pytest.mark.django_db
def test_provider_type_filter_limits_results(client, typed_providers):
    response = client.get(
        reverse("providers:list"),
        {"state": "South Carolina", "provider_type": "Family Child Care Home"},
    )

    names = [provider.provider_name for provider in response.context["providers"]]
    assert names == ["Home B"]


@pytest.fixture
def rated_providers(db):
    # Ratings deliberately out of canonical order to prove ordering is by the
    # quality gradient, not alphabetical.
    for name, rating in [("Okay", "C"), ("Best", "A+"), ("Bplus", "B+"), ("Good", "A")]:
        Provider.objects.create(
            provider_name=name,
            source_state="South Carolina",
            state_data={"sc_abc_quality_rating": rating},
        )
    Provider.objects.create(
        provider_name="Unrated",
        source_state="South Carolina",
        state_data={},
    )
    # Another state carrying the same key must not surface the SC filter.
    Provider.objects.create(
        provider_name="Georgia One",
        source_state="Georgia",
        state_data={"sc_abc_quality_rating": "A+"},
    )


@pytest.mark.django_db
def test_sc_rating_filter_only_offered_for_south_carolina(client, rated_providers):
    assert client.get(reverse("providers:list")).context["sc_ratings"] == []

    in_sc = client.get(reverse("providers:list"), {"state": "South Carolina"})
    assert in_sc.context["sc_ratings"] == ["A+", "A", "B+", "C"]

    in_ga = client.get(reverse("providers:list"), {"state": "Georgia"})
    assert in_ga.context["sc_ratings"] == []


@pytest.mark.django_db
def test_sc_rating_filter_limits_results(client, rated_providers):
    response = client.get(
        reverse("providers:list"),
        {"state": "South Carolina", "sc_rating": "A+"},
    )

    names = [provider.provider_name for provider in response.context["providers"]]
    assert names == ["Best"]


@pytest.mark.django_db
def test_sc_rating_ignored_for_other_state(client, rated_providers):
    # A non-SC state never applies the SC rating filter.
    response = client.get(
        reverse("providers:list"),
        {"state": "Georgia", "sc_rating": "A+"},
    )

    names = [provider.provider_name for provider in response.context["providers"]]
    assert names == ["Georgia One"]


@pytest.fixture
def named_providers(db):
    for name in ("Sunshine Daycare", "Cheraw Head Start", "Little Explorers Academy"):
        Provider.objects.create(provider_name=name, source_state="South Carolina")


@pytest.mark.django_db
def test_name_search_matches_substring(client, named_providers):
    response = client.get(reverse("providers:list"), {"q": "head"})

    names = [provider.provider_name for provider in response.context["providers"]]
    assert names == ["Cheraw Head Start"]


@pytest.mark.django_db
def test_name_search_is_fuzzy(client, named_providers):
    # "Sunshyne" is a typo for "Sunshine" and shares no substring, so only
    # trigram similarity can match it.
    response = client.get(reverse("providers:list"), {"q": "Sunshyne"})

    names = [provider.provider_name for provider in response.context["providers"]]
    assert "Sunshine Daycare" in names


@pytest.mark.django_db
def test_name_search_returns_nothing_for_no_match(client, named_providers):
    response = client.get(reverse("providers:list"), {"q": "zzzzzzz"})

    assert list(response.context["providers"]) == []


@pytest.mark.django_db
def test_name_search_combines_with_state_filter(client, named_providers):
    Provider.objects.create(provider_name="Sunshine Daycare", source_state="Georgia")

    response = client.get(
        reverse("providers:list"),
        {"state": "South Carolina", "q": "Sunshine"},
    )

    providers = list(response.context["providers"])
    assert [p.provider_name for p in providers] == ["Sunshine Daycare"]
    assert all(p.source_state == "South Carolina" for p in providers)


@pytest.fixture
def program_providers(db):
    Provider.objects.create(
        provider_name="Head Start One",
        source_state="South Carolina",
        state_data={"sc_program_participation": ["Head Start", "First Steps 4K"]},
    )
    Provider.objects.create(
        provider_name="Four-K Only",
        source_state="South Carolina",
        state_data={"sc_program_participation": ["First Steps 4K"]},
    )
    Provider.objects.create(
        provider_name="No Programs",
        source_state="South Carolina",
        state_data={},
    )


@pytest.mark.django_db
def test_sc_program_filter_only_offered_for_south_carolina(client, program_providers):
    assert client.get(reverse("providers:list")).context["sc_programs"] == []

    in_sc = client.get(reverse("providers:list"), {"state": "South Carolina"})
    assert in_sc.context["sc_programs"] == ["First Steps 4K", "Head Start"]


@pytest.mark.django_db
def test_sc_program_filter_matches_membership_in_array(client, program_providers):
    response = client.get(
        reverse("providers:list"),
        {"state": "South Carolina", "sc_program": "Head Start"},
    )

    names = [provider.provider_name for provider in response.context["providers"]]
    # Both providers that participate in Head Start (alone or combined).
    assert names == ["Head Start One"]


@pytest.mark.django_db
def test_sc_program_multiselect_requires_all_selected(client, program_providers):
    # AND semantics: only providers participating in *every* selected program.
    response = client.get(
        reverse("providers:list"),
        {"state": "South Carolina", "sc_program": ["Head Start", "First Steps 4K"]},
    )

    names = [provider.provider_name for provider in response.context["providers"]]
    assert names == ["Head Start One"]


@pytest.mark.django_db
def test_license_number_filter_matches_substring(client):
    Provider.objects.create(provider_name="A", license_number="716")
    Provider.objects.create(provider_name="B", license_number="22227")

    response = client.get(reverse("providers:list"), {"license_number": "716"})

    names = [provider.provider_name for provider in response.context["providers"]]
    assert names == ["A"]


@pytest.mark.django_db
def test_active_license_filter(client):
    Provider.objects.create(provider_name="Active", license_expiration="12/31/2999")
    Provider.objects.create(provider_name="Expired", license_expiration="1/1/2000")
    Provider.objects.create(provider_name="No License", license_expiration=None)

    response = client.get(reverse("providers:list"), {"active": "1"})

    names = [provider.provider_name for provider in response.context["providers"]]
    assert names == ["Active"]


@pytest.fixture
def ny_providers(db):
    Provider.objects.create(
        provider_name="Albany Infants",
        source_state="NY",
        infant="8",
        toddler="0",
        capacity="8",
        state_data={"ny_region_code": "ARO", "ny_school_district_name": "Albany"},
    )
    Provider.objects.create(
        provider_name="Buffalo Mixed",
        source_state="NY",
        infant="4",
        toddler="6",
        # Thousands separator must still parse as a positive number.
        capacity="1,100",
        state_data={"ny_region_code": "BRO", "ny_school_district_name": "Buffalo"},
    )
    Provider.objects.create(
        provider_name="No Capacity",
        source_state="NY",
        infant="0",
        toddler="0",
        capacity="0",
        state_data={"ny_region_code": "ARO", "ny_school_district_name": "Albany"},
    )


@pytest.mark.django_db
def test_ny_filters_only_offered_for_new_york(client, ny_providers):
    Provider.objects.create(provider_name="SC One", source_state="South Carolina")

    # No state chosen, and a non-NY state: NY options are withheld.
    assert client.get(reverse("providers:list")).context["ny_regions"] == []
    in_sc = client.get(reverse("providers:list"), {"state": "South Carolina"})
    assert in_sc.context["ny_regions"] == []
    assert in_sc.context["ny_age_buckets"] == []

    in_ny = client.get(reverse("providers:list"), {"state": "NY"})
    assert in_ny.context["ny_regions"] == ["ARO", "BRO"]
    assert in_ny.context["ny_districts"] == ["Albany", "Buffalo"]
    assert in_ny.context["ny_age_buckets"] == [
        ("infant", "Infant"),
        ("toddler", "Toddler"),
        ("preschool", "Preschool"),
        ("school", "School-age"),
    ]


@pytest.mark.django_db
def test_ny_region_filter_limits_results(client, ny_providers):
    response = client.get(
        reverse("providers:list"),
        {"state": "NY", "ny_region": "BRO"},
    )

    names = [provider.provider_name for provider in response.context["providers"]]
    assert names == ["Buffalo Mixed"]


@pytest.mark.django_db
def test_ny_district_filter_limits_results(client, ny_providers):
    response = client.get(
        reverse("providers:list"),
        {"state": "NY", "ny_district": "Albany"},
    )

    names = [provider.provider_name for provider in response.context["providers"]]
    assert names == ["Albany Infants", "No Capacity"]


@pytest.mark.django_db
def test_ny_age_filter_keeps_only_positive_buckets(client, ny_providers):
    # Only providers with infant capacity > 0 (No Capacity has infant="0").
    response = client.get(
        reverse("providers:list"),
        {"state": "NY", "ny_age": "infant"},
    )

    names = [provider.provider_name for provider in response.context["providers"]]
    assert names == ["Albany Infants", "Buffalo Mixed"]


@pytest.mark.django_db
def test_ny_age_multiselect_requires_all_positive(client, ny_providers):
    # AND semantics: capacity > 0 in *every* selected age group.
    response = client.get(
        reverse("providers:list"),
        {"state": "NY", "ny_age": ["infant", "toddler"]},
    )

    names = [provider.provider_name for provider in response.context["providers"]]
    assert names == ["Buffalo Mixed"]


@pytest.mark.django_db
def test_ny_age_filter_ignored_for_other_state(client, ny_providers):
    # The age-group filter is gated on New York; for another state it does nothing.
    Provider.objects.create(
        provider_name="SC Infant",
        source_state="South Carolina",
        infant="5",
    )

    response = client.get(
        reverse("providers:list"),
        {"state": "South Carolina", "ny_age": "infant"},
    )

    names = [provider.provider_name for provider in response.context["providers"]]
    assert names == ["SC Infant"]


@pytest.mark.django_db
def test_has_capacity_filter_applies_across_states(client):
    # Base filter, no state selected: positive capacity only, commas tolerated,
    # blank/zero excluded.
    Provider.objects.create(
        provider_name="Big",
        source_state="South Carolina",
        capacity="1,100",
    )
    Provider.objects.create(provider_name="Zero", source_state="NY", capacity="0")
    Provider.objects.create(provider_name="Blank", source_state="NY", capacity="")

    response = client.get(reverse("providers:list"), {"has_capacity": "1"})

    names = [provider.provider_name for provider in response.context["providers"]]
    assert names == ["Big"]


@pytest.fixture
def va_providers(db):
    # Ratings out of canonical order to prove ordering is by the quality gradient.
    Provider.objects.create(
        provider_name="Meets Place",
        source_state="VA",
        state_data={
            "va_quality_rating": "Meets Expectations",
            "va_public_funding": "VPI; Head Start; VA CCSP",
        },
    )
    Provider.objects.create(
        provider_name="Top Place",
        source_state="VA",
        state_data={
            "va_quality_rating": "Exceeds Expectations",
            # "Early Head Start" must not be matched by a "Head Start" filter.
            "va_public_funding": "Early Head Start; VA CCSP",
        },
    )
    Provider.objects.create(
        provider_name="Unrated Place",
        source_state="VA",
        state_data={},
    )
    # Another state carrying the same keys must not surface the VA filters.
    Provider.objects.create(
        provider_name="Carolina One",
        source_state="South Carolina",
        state_data={"va_quality_rating": "Meets Expectations"},
    )


@pytest.mark.django_db
def test_va_quality_filter_only_offered_for_virginia(client, va_providers):
    assert client.get(reverse("providers:list")).context["va_quality_ratings"] == []

    in_va = client.get(reverse("providers:list"), {"state": "VA"})
    # Canonical quality order, limited to ratings present in the data.
    assert in_va.context["va_quality_ratings"] == [
        "Exceeds Expectations",
        "Meets Expectations",
    ]

    in_sc = client.get(reverse("providers:list"), {"state": "South Carolina"})
    assert in_sc.context["va_quality_ratings"] == []


@pytest.mark.django_db
def test_va_quality_filter_limits_results(client, va_providers):
    response = client.get(
        reverse("providers:list"),
        {"state": "VA", "va_quality": "Exceeds Expectations"},
    )

    names = [provider.provider_name for provider in response.context["providers"]]
    assert names == ["Top Place"]


@pytest.mark.django_db
def test_va_funding_filter_only_offered_for_virginia(client, va_providers):
    assert client.get(reverse("providers:list")).context["va_fundings"] == []

    in_va = client.get(reverse("providers:list"), {"state": "VA"})
    # Distinct tokens split out of the ';'-delimited strings, sorted.
    assert in_va.context["va_fundings"] == [
        "Early Head Start",
        "Head Start",
        "VA CCSP",
        "VPI",
    ]


@pytest.mark.django_db
def test_va_funding_filter_matches_delimited_token_not_substring(client, va_providers):
    # "Head Start" must match only the provider that funds it, not the one whose
    # funding string contains "Early Head Start".
    response = client.get(
        reverse("providers:list"),
        {"state": "VA", "va_funding": "Head Start"},
    )

    names = [provider.provider_name for provider in response.context["providers"]]
    assert names == ["Meets Place"]


@pytest.mark.django_db
def test_va_funding_multiselect_requires_all(client, va_providers):
    # AND semantics: only providers receiving *every* selected funding program.
    response = client.get(
        reverse("providers:list"),
        {"state": "VA", "va_funding": ["Head Start", "VA CCSP"]},
    )

    names = [provider.provider_name for provider in response.context["providers"]]
    assert names == ["Meets Place"]
