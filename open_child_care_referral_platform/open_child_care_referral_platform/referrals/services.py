"""Ingest referral requests from an external system.

Payload contract (v1)::

    {
      "request_id": "abc-123",            # required — idempotency key
      "family": {                          # required
        "name": "Jordan Rivera",
        "email": "jordan@example.com",     # required — family User id + dedup key
        "phone": "555-0100"
      },
      "children": [                        # optional
        {
          "external_id": "child-1",        # optional — disambiguates idempotency
          "first_name": "Sam",
          "last_name": "Rivera",
          "date_of_birth": "2021-04-12",   # ISO date
          "relationship": "child",         # a Child.Relationship value
          "in_school": false,
          "referral_need": "need_assistance",  # a Child.ReferralNeed value
          "care_schedule": {"monday": [["07:30", "09:00"]]},
          "schools": [
            {"institution_name": "Lincoln Elementary", "city": "Columbus",
             "state": "OH", "grade_level": "K",
             "school_year_start": "2026-08-20", "school_year_end": "2027-06-05"}
          ]
        }
      ]
    }

One :class:`Referral` is created per child, keyed by
``external_id = f"{request_id}:{child_external_id or index}"``. Re-posting the
same request is therefore idempotent: an existing referral for that key short-
circuits, so no duplicate users, children, schools, or referrals are created.
The whole operation runs in one transaction.
"""

from __future__ import annotations

from typing import Any

from django.contrib.auth.models import Group
from django.db import transaction
from django.utils.dateparse import parse_date

from open_child_care_referral_platform.referrals.models import Child
from open_child_care_referral_platform.referrals.models import Referral
from open_child_care_referral_platform.referrals.models import School
from open_child_care_referral_platform.users.models import User
from open_child_care_referral_platform.users.roles import FAMILY_GROUP


def _require(data: dict[str, Any], key: str) -> Any:
    value = data.get(key)
    if not value:
        msg = f"'{key}' is required."
        raise ValueError(msg)
    return value


def _validate_choice(value: Any, valid: set[str], default: str, label: str) -> str:
    if not value:
        return default
    if value not in valid:
        msg = f"{value!r} is not a valid {label}."
        raise ValueError(msg)
    return value


def _parse_date(value: Any) -> Any:
    return parse_date(value) if value else None


@transaction.atomic
def ingest_referral_request(payload: dict[str, Any]) -> list[Referral]:
    """Create a family user, children, schools, and one referral per child.

    Idempotent on ``request_id`` (+ each child's ``external_id``/index). Raises
    ``ValueError`` on malformed input.
    """
    if not isinstance(payload, dict):
        # Malformed input → ValueError so the view returns HTTP 400, not a 500.
        msg = "Payload must be a JSON object."
        raise ValueError(msg)  # noqa: TRY004
    request_id = _require(payload, "request_id")
    family = payload.get("family")
    if not isinstance(family, dict):
        msg = "'family' object is required."
        raise ValueError(msg)  # noqa: TRY004
    email = _require(family, "email")

    user = _upsert_family_user(family, email)

    referrals: list[Referral] = []
    for index, child_data in enumerate(payload.get("children") or []):
        external_id = f"{request_id}:{child_data.get('external_id') or index}"
        referrals.append(_upsert_child_referral(user, external_id, child_data))
    return referrals


def _upsert_family_user(family: dict[str, Any], email: str) -> User:
    user, created = User.objects.get_or_create(
        email=email,
        defaults={"name": family.get("name", "")},
    )
    # New accounts get no usable password until the family claims them (Task 08).
    # Existing accounts are left alone, so a password set at claim-time survives
    # re-ingestion. (A fresh user's password is "", which Django paradoxically
    # reports as usable, so key off ``created`` rather than has_usable_password.)
    if created:
        user.set_unusable_password()
    if family.get("name"):
        user.name = family["name"]
    if family.get("phone"):
        user.phone = family["phone"]
    user.save()
    user.groups.add(Group.objects.get(name=FAMILY_GROUP))
    return user


def _upsert_child_referral(
    user: User,
    external_id: str,
    child_data: dict[str, Any],
) -> Referral:
    existing = Referral.objects.filter(external_id=external_id).first()
    if existing is not None:
        # Already ingested this child-request; don't duplicate child/schools.
        return existing
    child = _create_child(user, child_data)
    return Referral.objects.create(
        child=child,
        external_id=external_id,
        source=Referral.Source.INGESTED,
        status=Referral.Status.NEW,
    )


def _create_child(user: User, child_data: dict[str, Any]) -> Child:
    child = Child.objects.create(
        family=user,
        first_name=child_data.get("first_name", ""),
        last_name=child_data.get("last_name", ""),
        date_of_birth=_parse_date(child_data.get("date_of_birth")),
        relationship=_validate_choice(
            child_data.get("relationship"),
            set(Child.Relationship.values),
            Child.Relationship.CHILD,
            "relationship",
        ),
        in_school=bool(child_data.get("in_school", False)),
        referral_need=_validate_choice(
            child_data.get("referral_need"),
            set(Child.ReferralNeed.values),
            Child.ReferralNeed.NEED_ASSISTANCE,
            "referral_need",
        ),
        care_schedule=child_data.get("care_schedule") or {},
    )
    for school_data in child_data.get("schools") or []:
        _create_school(child, school_data)
    return child


def _create_school(child: Child, school_data: dict[str, Any]) -> None:
    School.objects.create(
        child=child,
        institution_name=school_data.get("institution_name", ""),
        street=school_data.get("street", ""),
        street_2=school_data.get("street_2", ""),
        city=school_data.get("city", ""),
        state=school_data.get("state", ""),
        postal=school_data.get("postal", ""),
        grade_level=school_data.get("grade_level", ""),
        school_year_start=_parse_date(school_data.get("school_year_start")),
        school_year_end=_parse_date(school_data.get("school_year_end")),
    )
