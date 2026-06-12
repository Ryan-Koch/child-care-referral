"""Create the role groups (idempotent). Mirrors the data migration so an existing
database can be brought up to date without re-running migrations."""

from typing import Any

from django.core.management.base import BaseCommand

from open_child_care_referral_platform.users.roles import COORDINATOR_GROUP
from open_child_care_referral_platform.users.roles import FAMILY_GROUP
from open_child_care_referral_platform.users.roles import ensure_roles


class Command(BaseCommand):
    help = "Ensure the Coordinator and Family role groups exist (idempotent)."

    def handle(self, *args: Any, **options: Any) -> None:
        ensure_roles()
        self.stdout.write(
            self.style.SUCCESS(f"Roles ensured: {COORDINATOR_GROUP}, {FAMILY_GROUP}."),
        )
