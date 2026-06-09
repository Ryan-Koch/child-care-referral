from django import forms

from open_child_care_referral_platform.referrals.models import Referral
from open_child_care_referral_platform.referrals.models import ReferralProvider


class ReferralNotesForm(forms.ModelForm):
    class Meta:
        model = Referral
        fields = ["notes"]


class ReferralProviderForm(forms.ModelForm):
    """Per-saved-provider status + notes edit."""

    class Meta:
        model = ReferralProvider
        fields = ["status", "notes"]
