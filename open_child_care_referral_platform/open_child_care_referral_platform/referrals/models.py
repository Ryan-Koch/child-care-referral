"""Referral domain models.

Task 02 adds the family-side domain (:class:`Child`, :class:`School`). Task 03
adds :class:`Referral` and :class:`ReferralProvider`.

Unlike the ``providers`` app (raw scraped text, ``null=True`` ``TextField``s),
these are application-authored, typed rows: real field types with ``blank=True``
and no ``null`` on string fields (keeps ruff DJ001 satisfied without an ignore).
"""

from django.db import models
from model_utils.models import TimeStampedModel


class Child(TimeStampedModel):
    """A child belonging to a family (a ``users.User`` in the Family group).

    Carries the context that drives referrals: in-school status, the kind of
    help needed, any provider already used for care, and a weekly care schedule.
    Referrals are per-child (see Task 03).
    """

    class Relationship(models.TextChoices):
        CHILD = "child", "Child"
        STEPCHILD = "stepchild", "Stepchild"
        FOSTER = "foster", "Foster Child"
        GUARDIAN_WARD = "guardian_ward", "Legal Guardian/Ward"

    class ReferralNeed(models.TextChoices):
        PROVIDER_ACTIVE = "provider_active", "Provider Active"
        PROVIDER_CHOSEN = "provider_chosen", "Provider Chosen"
        NEED_ASSISTANCE = "need_assistance", "Need Assistance"
        SELF_SERVICE = "self_service", "Self Service"

    family = models.ForeignKey(
        "users.User",
        on_delete=models.CASCADE,
        related_name="children",
    )
    first_name = models.CharField(max_length=255, blank=True)
    last_name = models.CharField(max_length=255, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    relationship = models.CharField(
        max_length=32,
        choices=Relationship.choices,
        default=Relationship.CHILD,
    )
    in_school = models.BooleanField(default=False)
    referral_need = models.CharField(
        max_length=32,
        choices=ReferralNeed.choices,
        default=ReferralNeed.NEED_ASSISTANCE,
    )
    active_provider = models.ForeignKey(
        "providers.Provider",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="children_in_care",
    )
    # Shape: {"<weekday>": [["HH:MM", "HH:MM"], ...]} — one or more [start, end]
    # ranges per day (e.g. before- and after-school care); empty == {}. Validation
    # is deferred to the forms in Tasks 06/09; stored loosely for now.
    care_schedule = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name_plural = "children"

    def __str__(self) -> str:
        return f"{self.first_name} {self.last_name}".strip() or f"Child #{self.pk}"


class School(TimeStampedModel):
    """A school attended by a :class:`Child`.

    Modeled as a FK (typically one school per child, but kept flexible).
    """

    child = models.ForeignKey(
        Child,
        on_delete=models.CASCADE,
        related_name="schools",
    )
    institution_name = models.CharField(max_length=255, blank=True)
    street = models.CharField(max_length=255, blank=True)
    street_2 = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=128, blank=True)
    state = models.CharField(max_length=64, blank=True)
    postal = models.CharField(max_length=16, blank=True)
    grade_level = models.CharField(max_length=64, blank=True)
    school_year_start = models.DateField(null=True, blank=True)
    school_year_end = models.DateField(null=True, blank=True)

    def __str__(self) -> str:
        return self.institution_name or f"School #{self.pk}"
