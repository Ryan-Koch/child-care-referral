"""Ingest a referral request from a JSON file or stdin.

Calls the same service the HTTP endpoint uses. Mirrors the ``load_state_data``
command; in Docker, pipe a file in on stdin::

    just manage ingest_referral_request < request.json
"""

import json
import sys
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand
from django.core.management.base import CommandError
from django.core.management.base import CommandParser

from open_child_care_referral_platform.referrals.services import ingest_referral_request


class Command(BaseCommand):
    help = "Ingest a referral request from a JSON file (--path) or stdin."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--path",
            default=None,
            help="Path to the request JSON, or omit / '-' to read from stdin.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        path = options["path"]
        if path in (None, "-"):
            raw = sys.stdin.read()
        else:
            file_path = Path(path)
            if not file_path.exists():
                msg = f"File not found: {file_path}"
                raise CommandError(msg)
            raw = file_path.read_text(encoding="utf-8")

        try:
            payload = json.loads(raw)
            referrals = ingest_referral_request(payload)
        except (json.JSONDecodeError, ValueError, KeyError) as exc:
            msg = f"Ingestion failed: {exc}"
            raise CommandError(msg) from exc

        ids = ", ".join(str(referral.id) for referral in referrals)
        self.stdout.write(
            self.style.SUCCESS(f"Ingested {len(referrals)} referral(s): {ids}"),
        )
