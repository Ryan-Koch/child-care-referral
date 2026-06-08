import json

import pytest
from django.core.management import call_command

from open_child_care_referral_platform.providers.models import Inspection
from open_child_care_referral_platform.providers.models import Provider

LICENSED_RECORD = {
    "source_state": "South Carolina",
    "provider_url": "https://www.scchildcare.org/provider/4263/cheraw-head-start/",
    "sc_provider_id": "4263",
    "latitude": "34.6800838",
    "longitude": "-79.9049916",
    "provider_name": "Cheraw Head Start",
    "provider_type": "Child Care Center",
    "sc_abc_quality_rating": "A+",
    "license_number": "716",
    "county": "Chesterfield",
    "inspections": [
        {"date": "6/13/2025", "type": "Annual Review", "report_url": "/r/716.pdf"},
        {
            "date": "10/24/2024",
            "type": "Renewal Application",
            "report_url": "/r/716_ren.pdf",
            "sc_alert_count": 2,
            "sc_deficiencies": [{"severity": "Medium", "deficiency_type": "Records"}],
        },
    ],
}

# Unlicensed/exempt provider: no license_number, matched on sc_provider_id.
UNLICENSED_RECORD = {
    "source_state": "South Carolina",
    "provider_url": "https://www.scchildcare.org/provider/CC045778/ala/",
    "sc_provider_id": "CC045778",
    "provider_name": "Ala Enrichment Center",
    "provider_type": "Exempt Child Care Center",
    "status": "NOT LICENSED",
    "inspections": [],
}

# Virginia: real license_number, va_* extras, and nested inspections whose only
# mapped column is the date.
VA_RECORD = {
    "va_ID": "35291",
    "provider_name": "4 Rs Preschool",
    "address": "6745 Jefferson Street HAYMARKET, VA 20169",
    "phone": "(703) 754-2497",
    "provider_type": "Child Day Center",
    "va_license_type": "Two Year",
    "administrator": "Robyn Frazier",
    "hours": "9:00 a.m. - 3:30 p.m., Monday - Friday",
    "capacity": "26",
    "ages_served": "3 years - 6 years 11 months",
    "va_quality_rating": "4",
    "license_number": "1106312",
    "source_state": "VA",
    "provider_url": "https://legacy.dss.virginia.gov/facility/search/cc2.cgi?ID=35291",
    "inspections": [
        {
            "date": "May 13, 2026",
            "va_shsi": "No",
            "va_complaint_related": "No",
            "va_violations": "Yes",
        },
        {
            "date": "Jan. 30, 2025",
            "va_shsi": "No",
            "va_complaint_related": "No",
            "va_violations": "No",
        },
    ],
}

# New York: no license_number key at all; ny_facility_id doubles as the license.
NY_RECORD = {
    "source_state": "NY",
    "ny_facility_id": "31200",
    "provider_type": "FDC",
    "ny_region_code": "SRO",
    "county": "Oneida",
    "status": "Registration",
    "provider_name": "Huckabone, Kimberly",
    "license_begin_date": "08/01/2022",
    "license_expiration": "07/31/2026",
    "address": "Prospect, NY, 13435",
    "phone": "(315)790-9035",
    "license_holder": "Kimberly A. Huckabone",
    "ny_school_district_name": "Holland Patent",
    "school": "2",
    "capacity": "8",
    "provider_url": "https://hs.ocfs.ny.gov/dcfs/Profile/Index/31200",
}


def _load(tmp_path, records, state="south_carolina", **options):
    path = tmp_path / f"{state}.json"
    path.write_text(json.dumps(records), encoding="utf-8")
    call_command("load_state_data", state, path=str(path), **options)


@pytest.mark.django_db
def test_load_maps_columns_and_state_data(tmp_path):
    _load(tmp_path, [LICENSED_RECORD])

    provider = Provider.objects.get()
    # Cross-state keys land on real columns...
    assert provider.provider_name == "Cheraw Head Start"
    assert provider.license_number == "716"
    assert provider.source_state == "South Carolina"
    assert provider.latitude == "34.6800838"
    # ...and SC-specific keys are preserved verbatim in state_data.
    assert provider.state_data["sc_provider_id"] == "4263"
    assert provider.state_data["sc_abc_quality_rating"] == "A+"
    assert "inspections" not in provider.state_data


@pytest.mark.django_db
def test_load_creates_inspections_with_state_data(tmp_path):
    _load(tmp_path, [LICENSED_RECORD])

    provider = Provider.objects.get()
    assert provider.inspections.count() == len(LICENSED_RECORD["inspections"])
    renewal = provider.inspections.get(type="Renewal Application")
    assert renewal.report_url == "/r/716_ren.pdf"
    assert (
        renewal.state_data["sc_alert_count"]
        == LICENSED_RECORD["inspections"][1]["sc_alert_count"]
    )
    assert renewal.state_data["sc_deficiencies"][0]["severity"] == "Medium"


@pytest.mark.django_db
def test_rerun_updates_in_place_and_does_not_duplicate(tmp_path):
    _load(tmp_path, [LICENSED_RECORD])

    changed = {**LICENSED_RECORD, "provider_name": "Cheraw Head Start (Renamed)"}
    _load(tmp_path, [changed])

    provider = Provider.objects.get()  # still exactly one row
    assert provider.provider_name == "Cheraw Head Start (Renamed)"
    # Inspections are rebuilt, not duplicated.
    expected = len(LICENSED_RECORD["inspections"])
    assert provider.inspections.count() == expected
    assert Inspection.objects.count() == expected


@pytest.mark.django_db
def test_unlicensed_records_match_on_provider_id_not_collapsed(tmp_path):
    other = {
        **UNLICENSED_RECORD,
        "sc_provider_id": "CC099999",
        "provider_name": "Other",
    }
    records = [UNLICENSED_RECORD, other]

    _load(tmp_path, records)
    _load(tmp_path, records)  # idempotent

    # Distinct unlicensed providers, not merged onto one NULL-license row.
    unlicensed = Provider.objects.filter(license_number__isnull=True)
    assert unlicensed.count() == len(records)


@pytest.mark.django_db
def test_dry_run_writes_nothing(tmp_path):
    _load(tmp_path, [LICENSED_RECORD], dry_run=True)

    assert not Provider.objects.exists()
    assert not Inspection.objects.exists()


@pytest.mark.django_db
def test_new_york_uses_facility_id_as_license_number(tmp_path):
    _load(tmp_path, [NY_RECORD], state="new_york")

    provider = Provider.objects.get()
    # No license_number in the source, so ny_facility_id fills the column...
    assert provider.license_number == "31200"
    # ...and is kept verbatim in state_data too (duplicated for now).
    assert provider.state_data["ny_facility_id"] == "31200"
    # Cross-state keys land on real columns.
    assert provider.provider_name == "Huckabone, Kimberly"
    assert provider.source_state == "NY"
    assert provider.license_holder == "Kimberly A. Huckabone"
    assert provider.school == "2"
    # NY-specific keys are preserved verbatim in state_data.
    assert provider.state_data["ny_region_code"] == "SRO"
    assert provider.state_data["ny_school_district_name"] == "Holland Patent"


@pytest.mark.django_db
def test_new_york_rerun_matches_on_facility_id_not_duplicated(tmp_path):
    _load(tmp_path, [NY_RECORD], state="new_york")

    changed = {**NY_RECORD, "provider_name": "Huckabone, Kimberly (Renamed)"}
    _load(tmp_path, [changed], state="new_york")

    provider = Provider.objects.get()  # still exactly one row
    assert provider.provider_name == "Huckabone, Kimberly (Renamed)"


@pytest.mark.django_db
def test_virginia_maps_columns_and_state_data(tmp_path):
    _load(tmp_path, [VA_RECORD], state="virginia")

    provider = Provider.objects.get()
    # Cross-state keys land on real columns...
    assert provider.provider_name == "4 Rs Preschool"
    assert provider.license_number == "1106312"
    assert provider.source_state == "VA"
    assert provider.administrator == "Robyn Frazier"
    assert provider.ages_served == "3 years - 6 years 11 months"
    # ...and VA-specific keys are preserved verbatim in state_data.
    assert provider.state_data["va_ID"] == "35291"
    assert provider.state_data["va_license_type"] == "Two Year"
    assert provider.state_data["va_quality_rating"] == "4"
    assert "inspections" not in provider.state_data


@pytest.mark.django_db
def test_virginia_creates_inspections_with_state_data(tmp_path):
    _load(tmp_path, [VA_RECORD], state="virginia")

    provider = Provider.objects.get()
    assert provider.inspections.count() == len(VA_RECORD["inspections"])
    # Only the date maps to a real column; the rest is VA-specific state_data.
    inspection = provider.inspections.get(date="May 13, 2026")
    assert inspection.state_data["va_violations"] == "Yes"
    assert inspection.state_data["va_complaint_related"] == "No"


@pytest.mark.django_db
def test_virginia_rerun_updates_in_place_and_rebuilds_inspections(tmp_path):
    _load(tmp_path, [VA_RECORD], state="virginia")

    changed = {**VA_RECORD, "provider_name": "4 Rs Preschool (Renamed)"}
    _load(tmp_path, [changed], state="virginia")

    provider = Provider.objects.get()  # still exactly one row
    assert provider.provider_name == "4 Rs Preschool (Renamed)"
    # Inspections are rebuilt, not duplicated.
    expected = len(VA_RECORD["inspections"])
    assert provider.inspections.count() == expected
    assert Inspection.objects.count() == expected


@pytest.mark.django_db
def test_virginia_shared_license_number_stays_distinct(tmp_path):
    # A single VA license_number is shared across distinct facilities, so records
    # must be matched on the stable va_ID, not collapsed onto one row.
    other = {
        **VA_RECORD,
        "va_ID": "51359",
        "provider_name": "The Hope Center",
        "inspections": [],
    }
    records = [VA_RECORD, other]

    _load(tmp_path, records, state="virginia")
    _load(tmp_path, records, state="virginia")  # idempotent

    same_license = Provider.objects.filter(license_number=VA_RECORD["license_number"])
    assert same_license.count() == len(records)
    names = sorted(same_license.values_list("provider_name", flat=True))
    assert names == ["4 Rs Preschool", "The Hope Center"]
