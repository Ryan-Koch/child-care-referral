"""Account signal receivers."""

from allauth.account.models import EmailAddress
from allauth.account.signals import password_reset
from django.dispatch import receiver


@receiver(password_reset)
def verify_email_on_password_reset(sender, request, user, **kwargs):
    """Mark the email verified once a password reset completes.

    Completing the emailed reset proves control of the inbox, so the address is
    verified. This lets ingested family users (Task 07) who claim their account
    via the reset link sign in immediately under mandatory email verification.
    """
    email_obj, _created = EmailAddress.objects.get_or_create(
        user=user,
        email=user.email,
        defaults={"verified": True, "primary": True},
    )
    if not email_obj.verified:
        email_obj.verified = True
        email_obj.save(update_fields=["verified"])
