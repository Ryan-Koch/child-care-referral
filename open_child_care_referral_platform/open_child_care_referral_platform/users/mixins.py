"""Access-control mixins for role-gated views.

Importable by any app (identity lives in ``users``). Anonymous users are
redirected to login; an authenticated user outside the required group gets a
403; superusers always pass.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.mixins import UserPassesTestMixin

from open_child_care_referral_platform.users.roles import COORDINATOR_GROUP
from open_child_care_referral_platform.users.roles import FAMILY_GROUP

if TYPE_CHECKING:
    from django.http import HttpRequest


class _GroupRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Restrict a view to authenticated members of ``group_name``."""

    # Supplied by ``View`` at runtime; declared here for type checkers because
    # this mixin is composed onto views rather than subclassing ``View`` itself.
    request: HttpRequest
    group_name: str = ""

    def test_func(self) -> bool:
        user = self.request.user
        return user.is_authenticated and (
            user.is_superuser or user.groups.filter(name=self.group_name).exists()
        )


class CoordinatorRequiredMixin(_GroupRequiredMixin):
    group_name = COORDINATOR_GROUP


class FamilyRequiredMixin(_GroupRequiredMixin):
    group_name = FAMILY_GROUP
