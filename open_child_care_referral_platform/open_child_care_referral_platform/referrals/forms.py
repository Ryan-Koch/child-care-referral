from django import forms

from open_child_care_referral_platform.referrals.models import Message
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


class MessageForm(forms.ModelForm):
    """Post a single message to a referral thread (Task 10).

    Only ``body`` is user-supplied; ``referral`` and ``sender`` are set by the
    view. ``body`` is required, which rejects empty/whitespace-only posts.
    """

    class Meta:
        model = Message
        fields = ["body"]
        widgets = {
            "body": forms.Textarea(
                attrs={
                    "rows": 3,
                    "class": "form-control",
                    "placeholder": "Write a message…",
                },
            ),
        }
