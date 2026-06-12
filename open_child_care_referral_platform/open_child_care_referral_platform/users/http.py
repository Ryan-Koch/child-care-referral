"""Small HTTP helpers shared across apps."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.utils.http import url_has_allowed_host_and_scheme

if TYPE_CHECKING:
    from django.http import HttpRequest


def is_safe_next(request: HttpRequest, url: str) -> bool:
    """True if ``url`` is a safe same-site redirect target for ``request``.

    The shared guard behind every ``?next=`` round-trip (provider detail back
    link, family save redirect) so the host/scheme rules live in one place.
    """
    return bool(url) and url_has_allowed_host_and_scheme(
        url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    )
