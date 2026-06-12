"""Account-claim helper.

Ingested family users (Task 07) have no usable password. "Claiming" the account
reuses allauth's password-reset machinery: the emailed link lets the family set
a password and sign in. Lives in ``users`` so any app can trigger it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from allauth.account.forms import ResetPasswordForm

if TYPE_CHECKING:
    from django.http import HttpRequest

    from open_child_care_referral_platform.users.models import User


def send_account_claim_email(user: User, request: HttpRequest) -> bool:
    """Email ``user`` a password-reset ("claim your account") link.

    Returns whether the email was sent (False if the address didn't resolve to a
    user). Needs ``request`` so allauth can build the absolute link. In dev the
    link prints to the console.
    """
    form = ResetPasswordForm(data={"email": user.email})
    if not form.is_valid():
        return False
    form.save(request)
    return True
