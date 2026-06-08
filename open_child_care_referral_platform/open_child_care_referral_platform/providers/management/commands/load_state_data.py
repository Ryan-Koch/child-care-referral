"""Upsert a state's scraped child-care data into the database.

South Carolina and New York are wired up so far. The raw per-state JSON lives
outside the project root in ``state_ingestion_files/<state>.json``; each record is
mapped onto the cross-state :class:`Provider` columns, with everything
state-specific preserved verbatim under ``state_data``. Nested ``inspections``
become :class:`Inspection` rows.

The load is idempotent: providers are matched on ``license_number`` (scoped to
``source_state``), so re-running updates rows in place instead of duplicating
them. South Carolina records without a ``license_number`` (unlicensed/exempt
providers) fall back to the state's own stable ``sc_provider_id`` so they are not
collapsed onto one another. New York providers carry no license number at all, so
the state's stable ``ny_facility_id`` doubles as the ``license_number`` (and is
kept verbatim under ``state_data`` too).
"""

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand
from django.core.management.base import CommandError
from django.core.management.base import CommandParser
from django.db import transaction

from open_child_care_referral_platform.providers.models import Inspection
from open_child_care_referral_platform.providers.models import Provider


@dataclass
class MappedInspection:
    """An inspection split into real columns and leftover state-specific data."""

    columns: dict[str, Any]
    state_data: dict[str, Any]


@dataclass
class MappedProvider:
    """A provider record normalized into the shape the upsert loop consumes."""

    columns: dict[str, Any]
    state_data: dict[str, Any]
    inspections: list[MappedInspection]
    # Identity used only when ``license_number`` is missing: a key looked up
    # inside ``state_data`` (plus its value) so such records stay distinct.
    fallback_key: str
    fallback_value: Any


# Provider JSON keys that map onto real ``Provider`` columns (names line up
# 1:1). Every other key on the record is preserved under ``state_data``.
SC_PROVIDER_COLUMNS = frozenset(
    {
        "provider_name",
        "license_number",
        "provider_type",
        "status",
        "address",
        "latitude",
        "longitude",
        "phone",
        "administrator",
        "capacity",
        "hours",
        "county",
        "license_begin_date",
        "license_expiration",
        "source_state",
        "provider_url",
    },
)

# Inspection JSON keys that map onto real ``Inspection`` columns.
SC_INSPECTION_COLUMNS = frozenset({"date", "type", "report_url"})

# Stable per-record id used to match unlicensed providers (no license_number).
SC_FALLBACK_KEY = "sc_provider_id"


def _map_sc_inspection(raw: dict[str, Any]) -> MappedInspection:
    columns = {key: raw.get(key) for key in SC_INSPECTION_COLUMNS}
    state_data = {
        key: value for key, value in raw.items() if key not in SC_INSPECTION_COLUMNS
    }
    return MappedInspection(columns=columns, state_data=state_data)


def map_south_carolina(record: dict[str, Any]) -> MappedProvider:
    """Map one raw South Carolina record onto the normalized provider shape."""
    columns = {key: record.get(key) for key in SC_PROVIDER_COLUMNS}
    state_data = {
        key: value
        for key, value in record.items()
        if key not in SC_PROVIDER_COLUMNS and key != "inspections"
    }
    inspections = [_map_sc_inspection(raw) for raw in record.get("inspections") or []]
    return MappedProvider(
        columns=columns,
        state_data=state_data,
        inspections=inspections,
        fallback_key=SC_FALLBACK_KEY,
        fallback_value=record.get(SC_FALLBACK_KEY),
    )


# New York JSON keys that map onto real ``Provider`` columns (names line up 1:1).
# Everything else (the ``ny_*`` keys, including ``ny_facility_id``) is preserved
# under ``state_data``.
NY_PROVIDER_COLUMNS = frozenset(
    {
        "provider_name",
        "provider_type",
        "status",
        "address",
        "latitude",
        "longitude",
        "phone",
        "capacity",
        "county",
        "license_holder",
        "license_begin_date",
        "license_expiration",
        "infant",
        "toddler",
        "preschool",
        "school",
        "source_state",
        "provider_url",
    },
)

# New York has no license number, so this stable facility id is reused as the
# license_number and also matches unchanged-license re-runs.
NY_FALLBACK_KEY = "ny_facility_id"


def map_new_york(record: dict[str, Any]) -> MappedProvider:
    """Map one raw New York record onto the normalized provider shape.

    New York records have no ``license_number``; the stable ``ny_facility_id`` is
    reused as the ``license_number`` column so the row is identifiable and the
    idempotent upsert can match on it. The facility id is intentionally left in
    ``state_data`` as well, so it is duplicated across both for now.
    """
    columns = {key: record.get(key) for key in NY_PROVIDER_COLUMNS}
    facility_id = record.get(NY_FALLBACK_KEY)
    # No license_number in the source: fall back to the facility id.
    columns["license_number"] = record.get("license_number") or facility_id
    state_data = {
        key: value for key, value in record.items() if key not in NY_PROVIDER_COLUMNS
    }
    return MappedProvider(
        columns=columns,
        state_data=state_data,
        inspections=[],
        fallback_key=NY_FALLBACK_KEY,
        fallback_value=facility_id,
    )


# Registry of per-state mappers. Add a new entry here to support another state.
MAPPERS = {
    "new_york": map_new_york,
    "south_carolina": map_south_carolina,
}


class Command(BaseCommand):
    help = "Upsert a state's scraped child-care providers into the database."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "state",
            choices=sorted(MAPPERS),
            help="Which state's data to load (new_york or south_carolina so far).",
        )
        parser.add_argument(
            "--path",
            default=None,
            help=(
                "Path to the state JSON file, or '-' to read from stdin. Defaults "
                "to ../state_ingestion_files/<state>.json relative to the project "
                "root."
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Map and upsert inside a transaction, then roll back.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        state: str = options["state"]
        mapper = MAPPERS[state]
        records = self._load_records(state, options["path"])
        self.stdout.write(f"Loaded {len(records)} {state} records from source.")

        created = 0
        updated = 0
        inspections_written = 0
        with transaction.atomic():
            for record in records:
                mapped = mapper(record)
                _provider, was_created = self._upsert_provider(mapped)
                created += int(was_created)
                updated += int(not was_created)
                inspections_written += self._refresh_inspections(_provider, mapped)

            if options["dry_run"]:
                transaction.set_rollback(True)

        verb = "Would upsert" if options["dry_run"] else "Upserted"
        self.stdout.write(
            self.style.SUCCESS(
                f"{verb} {created + updated} providers "
                f"({created} created, {updated} updated) "
                f"and {inspections_written} inspections.",
            ),
        )

    def _load_records(self, state: str, path_opt: str | None) -> list[dict[str, Any]]:
        if path_opt == "-":
            raw = sys.stdin.read()
        else:
            path = Path(path_opt) if path_opt else self._default_path(state)
            if not path.exists():
                msg = f"State data file not found: {path}"
                raise CommandError(msg)
            raw = path.read_text(encoding="utf-8")

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            msg = f"Could not parse JSON from source: {exc}"
            raise CommandError(msg) from exc

        if not isinstance(data, list):
            msg = "Expected the state file to contain a JSON array of records."
            raise CommandError(msg)
        return data

    def _default_path(self, state: str) -> Path:
        return settings.BASE_DIR.parent / "state_ingestion_files" / f"{state}.json"

    def _upsert_provider(self, mapped: MappedProvider) -> tuple[Provider, bool]:
        provider = self._find_existing(mapped)
        was_created = provider is None
        if provider is None:
            provider = Provider()
        for field_name, value in mapped.columns.items():
            setattr(provider, field_name, value)
        provider.state_data = mapped.state_data
        provider.save()
        return provider, was_created

    def _find_existing(self, mapped: MappedProvider) -> Provider | None:
        source_state = mapped.columns.get("source_state")
        scoped = Provider.objects.filter(source_state=source_state)
        license_number = mapped.columns.get("license_number")
        if license_number:
            return scoped.filter(license_number=license_number).first()
        if mapped.fallback_value is None:
            return None
        lookup = {f"state_data__{mapped.fallback_key}": mapped.fallback_value}
        return scoped.filter(**lookup).first()

    def _refresh_inspections(self, provider: Provider, mapped: MappedProvider) -> int:
        # No stable inspection id in the source, so rebuild the set each run to
        # keep the upsert idempotent.
        provider.inspections.all().delete()
        rows = [
            Inspection(provider=provider, state_data=insp.state_data, **insp.columns)
            for insp in mapped.inspections
        ]
        Inspection.objects.bulk_create(rows)
        return len(rows)
