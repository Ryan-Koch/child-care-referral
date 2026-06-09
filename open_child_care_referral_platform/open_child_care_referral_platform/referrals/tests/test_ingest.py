from __future__ import annotations

import json
from copy import deepcopy
from http import HTTPStatus
from typing import Any

import pytest
from django.core.management import call_command
from django.urls import reverse

from open_child_care_referral_platform.referrals.models import Child
from open_child_care_referral_platform.referrals.models import Referral
from open_child_care_referral_platform.referrals.models import School
from open_child_care_referral_platform.referrals.services import ingest_referral_request
from open_child_care_referral_platform.users.models import User
from open_child_care_referral_platform.users.roles import FAMILY_GROUP
from open_child_care_referral_platform.users.roles import ensure_roles

_TOKEN = "secret-token"  # noqa: S105  (test value, not a real secret)

SAMPLE: dict[str, Any] = {
    "request_id": "req-1",
    "family": {
        "name": "Jordan Rivera",
        "email": "jordan@example.com",
        "phone": "555-0100",
    },
    "children": [
        {
            "external_id": "child-1",
            "first_name": "Sam",
            "last_name": "Rivera",
            "date_of_birth": "2021-04-12",
            "relationship": "child",
            "in_school": False,
            "referral_need": "need_assistance",
            "care_schedule": {"monday": [["07:30", "09:00"]]},
            "schools": [
                {
                    "institution_name": "Lincoln Elementary",
                    "city": "Columbus",
                    "state": "OH",
                },
            ],
        },
    ],
}


@pytest.mark.django_db
def test_ingest_creates_full_graph() -> None:
    ensure_roles()
    referrals = ingest_referral_request(deepcopy(SAMPLE))

    assert len(referrals) == 1
    referral = referrals[0]
    assert referral.source == Referral.Source.INGESTED
    assert referral.status == Referral.Status.NEW
    assert referral.external_id == "req-1:child-1"

    user = referral.child.family
    assert user.email == "jordan@example.com"
    assert user.name == "Jordan Rivera"
    assert user.phone == "555-0100"
    assert not user.has_usable_password()
    assert user.groups.filter(name=FAMILY_GROUP).exists()

    child = referral.child
    assert child.first_name == "Sam"
    assert str(child.date_of_birth) == "2021-04-12"
    assert child.care_schedule == {"monday": [["07:30", "09:00"]]}
    assert child.schools.count() == 1


@pytest.mark.django_db
def test_ingest_is_idempotent() -> None:
    ensure_roles()
    first = ingest_referral_request(deepcopy(SAMPLE))
    second = ingest_referral_request(deepcopy(SAMPLE))

    assert [r.pk for r in first] == [r.pk for r in second]
    assert User.objects.filter(email="jordan@example.com").count() == 1
    assert Referral.objects.count() == 1
    assert Child.objects.count() == 1
    assert School.objects.count() == 1


@pytest.mark.django_db
def test_ingest_requires_email() -> None:
    ensure_roles()
    payload = deepcopy(SAMPLE)
    del payload["family"]["email"]
    with pytest.raises(ValueError, match="email"):
        ingest_referral_request(payload)


@pytest.mark.django_db
def test_ingest_rejects_invalid_relationship() -> None:
    ensure_roles()
    payload = deepcopy(SAMPLE)
    payload["children"][0]["relationship"] = "bogus"
    with pytest.raises(ValueError, match="relationship"):
        ingest_referral_request(payload)
    # Atomic: nothing persisted on failure.
    assert not User.objects.filter(email="jordan@example.com").exists()


@pytest.mark.django_db
def test_ingest_view_creates_with_valid_token(client, settings) -> None:
    ensure_roles()
    settings.REFERRAL_INGEST_TOKEN = _TOKEN
    response = client.post(
        reverse("referrals:ingest"),
        data=json.dumps(SAMPLE),
        content_type="application/json",
        headers={"authorization": f"Bearer {_TOKEN}"},
    )
    assert response.status_code == HTTPStatus.CREATED
    assert Referral.objects.count() == 1


@pytest.mark.django_db
def test_ingest_view_rejects_bad_token(client, settings) -> None:
    settings.REFERRAL_INGEST_TOKEN = _TOKEN
    response = client.post(
        reverse("referrals:ingest"),
        data=json.dumps(SAMPLE),
        content_type="application/json",
        headers={"authorization": "Bearer wrong"},
    )
    assert response.status_code == HTTPStatus.UNAUTHORIZED
    assert not Referral.objects.exists()


@pytest.mark.django_db
def test_ingest_view_rejects_when_token_unset(client, settings) -> None:
    settings.REFERRAL_INGEST_TOKEN = ""
    response = client.post(
        reverse("referrals:ingest"),
        data=json.dumps(SAMPLE),
        content_type="application/json",
        headers={"authorization": "Bearer anything"},
    )
    assert response.status_code == HTTPStatus.UNAUTHORIZED


@pytest.mark.django_db
def test_ingest_view_rejects_malformed_json(client, settings) -> None:
    settings.REFERRAL_INGEST_TOKEN = _TOKEN
    response = client.post(
        reverse("referrals:ingest"),
        data="not json",
        content_type="application/json",
        headers={"authorization": f"Bearer {_TOKEN}"},
    )
    assert response.status_code == HTTPStatus.BAD_REQUEST


@pytest.mark.django_db
def test_management_command_ingests_from_file(tmp_path) -> None:
    ensure_roles()
    request_file = tmp_path / "request.json"
    request_file.write_text(json.dumps(SAMPLE))
    call_command("ingest_referral_request", path=str(request_file))
    assert Referral.objects.count() == 1
