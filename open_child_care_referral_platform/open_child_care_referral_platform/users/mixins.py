"""Access-control helpers for role-gated views.

Importable by any app (identity lives in ``users``). Anonymous users are
redirected to login; an authenticated user outside the required group gets a
403; superusers always pass. Provides both class-based mixins (for CBVs) and a
``coordinator_required`` decorator (for the small function-based action views).
"""

from __future__ import annotations

from functools import wraps
from typing import TYPE_CHECKING

from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.mixins import UserPassesTestMixin
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied

from open_child_care_referral_platform.users.roles import COORDINATOR_GROUP
from open_child_care_referral_platform.users.roles import FAMILY_GROUP

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import Any

    from django.http import HttpRequest
    from django.http import HttpResponseBase


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


def coordinator_required(
    view_func: Callable[..., HttpResponseBase],
) -> Callable[..., HttpResponseBase]:
    """Function-view counterpart of :class:`CoordinatorRequiredMixin`."""

    @wraps(view_func)
    def wrapped(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponseBase:
        user = request.user
        if not user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if not (
            user.is_superuser or user.groups.filter(name=COORDINATOR_GROUP).exists()
        ):
            raise PermissionDenied
        return view_func(request, *args, **kwargs)

    return wrapped
