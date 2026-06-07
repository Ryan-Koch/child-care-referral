from django.db import models
from model_utils.models import TimeStampedModel


class Provider(TimeStampedModel):
    """One scraped child-care provider.

    Common, cross-state fields are real columns; every state-specific field
    (``va_*``, ``tx_*``, ``ca_*``, ...) lives in ``state_data``. Everything is
    optional except the primary key; raw scraped values are stored as-is and are
    typed/cleaned in a later transform pass.
    """

    # ---- common / cross-state fields (scalars -> TextField) ----
    provider_name = models.TextField(null=True, blank=True)
    license_number = models.TextField(null=True, blank=True)
    license_holder = models.TextField(null=True, blank=True)
    provider_type = models.TextField(null=True, blank=True)
    status = models.TextField(null=True, blank=True)
    status_date = models.TextField(null=True, blank=True)
    sutq_rating = models.TextField(null=True, blank=True)
    address = models.TextField(null=True, blank=True)
    latitude = models.TextField(null=True, blank=True)
    longitude = models.TextField(null=True, blank=True)
    phone = models.TextField(null=True, blank=True)
    email = models.TextField(null=True, blank=True)
    provider_website = models.TextField(null=True, blank=True)
    administrator = models.TextField(null=True, blank=True)
    capacity = models.TextField(null=True, blank=True)
    hours = models.TextField(null=True, blank=True)
    ages_served = models.TextField(null=True, blank=True)
    infant = models.TextField(null=True, blank=True)
    toddler = models.TextField(null=True, blank=True)
    preschool = models.TextField(null=True, blank=True)
    school = models.TextField(null=True, blank=True)
    county = models.TextField(null=True, blank=True)
    scholarships_accepted = models.TextField(null=True, blank=True)
    license_begin_date = models.TextField(null=True, blank=True)
    license_expiration = models.TextField(null=True, blank=True)
    languages = models.JSONField(null=True, blank=True)
    deficiencies = models.JSONField(null=True, blank=True)

    # ---- tracking / debug ----
    source_state = models.TextField(null=True, blank=True, db_index=True)
    provider_url = models.TextField(null=True, blank=True)

    # ---- everything state-specific (va_*, tx_*, ca_*, ...) ----
    state_data = models.JSONField(default=dict, blank=True)

    def __str__(self) -> str:
        return self.provider_name or f"Provider #{self.pk}"


class Inspection(TimeStampedModel):
    """A single inspection/visit record belonging to a :class:`Provider`."""

    provider = models.ForeignKey(
        Provider,
        on_delete=models.CASCADE,
        related_name="inspections",
        null=True,
        blank=True,
    )

    # ---- common inspection fields ----
    date = models.TextField(null=True, blank=True)
    type = models.TextField(null=True, blank=True)
    original_status = models.TextField(null=True, blank=True)
    corrective_status = models.TextField(null=True, blank=True)
    status_updated = models.TextField(null=True, blank=True)
    report_url = models.TextField(null=True, blank=True)

    # ---- everything state-specific (va_*, md_*, sc_*, ...) ----
    state_data = models.JSONField(default=dict, blank=True)

    def __str__(self) -> str:
        label = f"{self.type or ''} {self.date or ''}".strip()
        return label or f"Inspection #{self.pk}"
