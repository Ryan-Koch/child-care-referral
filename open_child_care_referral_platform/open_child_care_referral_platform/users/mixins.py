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
from open_child_care_referral_platform.users.roles import user_in_group

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
        return user.is_superuser or user_in_group(user, self.group_name)


class CoordinatorRequiredMixin(_GroupRequiredMixin):
    group_name = COORDINATOR_GROUP


class FamilyRequiredMixin(_GroupRequiredMixin):
    group_name = FAMILY_GROUP


def _require_group(
    group_name: str,
) -> Callable[[Callable[..., HttpResponseBase]], Callable[..., HttpResponseBase]]:
    """Build a function-view decorator gating on membership of ``group_name``."""

    def decorator(
        view_func: Callable[..., HttpResponseBase],
    ) -> Callable[..., HttpResponseBase]:
        @wraps(view_func)
        def wrapped(
            request: HttpRequest,
            *args: Any,
            **kwargs: Any,
        ) -> HttpResponseBase:
            user = request.user
            if not user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            if not (user.is_superuser or user_in_group(user, group_name)):
                raise PermissionDenied
            return view_func(request, *args, **kwargs)

        return wrapped

    return decorator


# Function-view counterparts of the mixins above.
coordinator_required = _require_group(COORDINATOR_GROUP)
family_required = _require_group(FAMILY_GROUP)
