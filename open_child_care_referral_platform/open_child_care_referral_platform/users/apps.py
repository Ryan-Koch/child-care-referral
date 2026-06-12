from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class UsersConfig(AppConfig):
    name = "open_child_care_referral_platform.users"
    verbose_name = _("Users")

    def ready(self):
        """Wire up signal receivers (email verification on password reset)."""
        from open_child_care_referral_platform.users import signals  # noqa: F401
