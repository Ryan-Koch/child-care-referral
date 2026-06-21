from http import HTTPStatus

import pytest
from django.urls import reverse

from open_child_care_referral_platform.providers import detail
from open_child_care_referral_platform.providers.models import Inspection
from open_child_care_referral_platform.providers.models import Provider
from open_child_care_referral_platform.users.tests.factories import make_family


# ---------------------------------------------------------------------------
# Quality-rating view-model, state by state
# ---------------------------------------------------------------------------
def test_quality_summary_sc_grade():
    provider = Provider(
        source_state="South Carolina",
        state_data={
            "sc_abc_quality_rating": "A+",
            "sc_abc_rating_history": [{"date": "8/28/2024", "rating": "A+"}],
        },
    )
    quality = detail.quality_summary(provider)
    assert quality is not None
    assert quality["kind"] == "grade"
    assert quality["is_rated"] is True
    assert quality["rating"] == "A+"
    assert quality["history"] == [{"date": "8/28/2024", "rating": "A+"}]


def test_quality_summary_sc_pending_is_not_rated():
    provider = Provider(
        source_state="South Carolina",
        state_data={"sc_abc_quality_rating": "P"},
    )
    quality = detail.quality_summary(provider)
    assert quality is not None
    assert quality["is_rated"] is False
    assert quality["status_label"] == "Pending"


def test_quality_summary_va_tier_with_domains():
    provider = Provider(
        source_state="VA",
        state_data={
            "va_quality_rating": "Meets Expectations",
            "va_total_points": "505",
            "va_interactions_points": "505",
            "va_curriculum_points": "0",
        },
    )
    quality = detail.quality_summary(provider)
    assert quality is not None
    assert quality["kind"] == "tier"
    assert quality["is_rated"] is True
    assert quality["rating"] == "Meets Expectations"
    interactions = quality["domains"][0]
    assert interactions["label"] == "Teacher-child interactions"
    # The largest domain fills the bar.
    assert interactions["pct"] == "100%"


def test_quality_summary_va_unrated_keeps_system_without_rating():
    provider = Provider(source_state="VA", state_data={})
    quality = detail.quality_summary(provider)
    assert quality is not None
    assert quality["is_rated"] is False
    assert quality["domains"] == []


def test_quality_summary_ny_has_no_system():
    provider = Provider(source_state="NY", state_data={"ny_facility_id": "1"})
    assert detail.quality_summary(provider) is None


# ---------------------------------------------------------------------------
# Compliance and inspection findings, state by state
# ---------------------------------------------------------------------------
def test_compliance_summary_none_without_inspections():
    provider = Provider(source_state="NY")
    assert detail.compliance_summary(provider, []) is None


def test_compliance_summary_sc_parses_deficiencies():
    deficiencies = [
        {
            "deficiency_type": "Child Records",
            "severity": "Medium",
            "resolved": "Yes",
            "date_resolved": "10/30/2024",
        },
        {
            "deficiency_type": "Staff Requirements",
            "severity": "High",
            "resolved": "No",
        },
    ]
    open_count = sum(1 for item in deficiencies if item["resolved"] == "No")
    provider = Provider(source_state="South Carolina", status="Licensed")
    inspections = [
        Inspection(
            type="Annual Review",
            date="10/24/2024",
            state_data={"sc_deficiencies": deficiencies},
        ),
        Inspection(type="Complaint", date="1/2/2023", state_data={}),
    ]

    summary = detail.compliance_summary(provider, inspections)

    assert summary is not None
    assert summary["kind"] == "sc"
    assert summary["expandable"] is True
    first = summary["rows"][0]
    assert first["deficiency_count"] == len(deficiencies)
    assert first["open_count"] == open_count
    assert {f["severity_level"] for f in first["findings"]} == {"medium", "high"}
    # The deficiency-free inspection is flagged clean.
    assert summary["rows"][1]["clean"] is True
    open_stat = next(s for s in summary["stats"] if s["label"] == "Open deficiencies")
    assert open_stat["value"] == str(open_count)
    assert open_stat["warn"] is True


def test_compliance_summary_va_flat_rows():
    rows_data = [
        {"date": "May 13, 2026", "va_violations": "Yes", "va_complaint_related": "No"},
        {"date": "Jan 30, 2025", "va_violations": "No"},
    ]
    with_violations = sum(1 for item in rows_data if item["va_violations"] == "Yes")
    provider = Provider(source_state="VA")
    inspections = [
        Inspection(
            date=item["date"],
            state_data={k: v for k, v in item.items() if k != "date"},
        )
        for item in rows_data
    ]

    summary = detail.compliance_summary(provider, inspections)

    assert summary is not None
    assert summary["kind"] == "va"
    assert summary["expandable"] is False
    assert summary["rows"][0]["violations"] is True
    assert summary["rows"][1]["violations"] is False
    viol_stat = next(s for s in summary["stats"] if s["label"] == "With violations")
    assert viol_stat["value"] == str(with_violations)


# ---------------------------------------------------------------------------
# Humanizing raw state_data keys
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("sc_abc_quality_rating", "ABC Quality Rating"),
        ("va_ID", "ID"),
        ("ny_school_district_name", "School District Name"),
        ("unprefixed_field", "Unprefixed Field"),
    ],
)
def test_humanize_state_key(key, expected):
    assert detail.humanize_state_key(key) == expected


# ---------------------------------------------------------------------------
# End-to-end rendering of the detail page, one provider per state
# ---------------------------------------------------------------------------
@pytest.mark.django_db
def test_detail_ny_hides_compliance_and_shows_no_quality(client):
    provider = Provider.objects.create(
        provider_name="Holland Patent FDC",
        source_state="NY",
        state_data={"ny_facility_id": "31200"},
    )

    response = client.get(reverse("providers:detail", kwargs={"pk": provider.pk}))

    assert response.status_code == HTTPStatus.OK
    content = response.content.decode()
    assert response.context["show_compliance"] is False
    assert 'data-tab="compliance"' not in content
    assert "No statewide quality rating in New York" in content


@pytest.mark.django_db
def test_detail_va_renders_quality_domains_and_compliance(client):
    provider = Provider.objects.create(
        provider_name="Children of America",
        source_state="VA",
        state_data={
            "va_quality_rating": "Meets Expectations",
            "va_total_points": "505",
            "va_interactions_points": "505",
            "va_curriculum_points": "0",
        },
    )
    Inspection.objects.create(
        provider=provider,
        date="May 13, 2026",
        state_data={"va_violations": "Yes"},
    )

    response = client.get(reverse("providers:detail", kwargs={"pk": provider.pk}))

    content = response.content.decode()
    assert response.context["show_compliance"] is True
    assert "Meets Expectations" in content
    assert "Teacher-child interactions" in content
    assert 'data-pct="100%"' in content


@pytest.mark.django_db
def test_detail_shows_referral_card_for_family(client):
    provider = Provider.objects.create(provider_name="Sunshine FDC", source_state="NY")
    client.force_login(make_family())

    response = client.get(reverse("providers:detail", kwargs={"pk": provider.pk}))

    content = response.content.decode()
    # A family with no children still gets the referral card + add-a-child prompt.
    assert 'class="cd-side-title">Referral' in content
    assert reverse("referrals:family_add_child") in content


@pytest.mark.django_db
def test_detail_hides_referral_card_for_anonymous(client):
    provider = Provider.objects.create(provider_name="Sunshine FDC", source_state="NY")

    response = client.get(reverse("providers:detail", kwargs={"pk": provider.pk}))

    content = response.content.decode()
    assert 'class="cd-side-title">Referral' not in content
    assert reverse("referrals:family_add_child") not in content
