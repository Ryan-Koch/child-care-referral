from django import forms

from open_child_care_referral_platform.referrals.models import Child
from open_child_care_referral_platform.referrals.models import Message
from open_child_care_referral_platform.referrals.models import Referral
from open_child_care_referral_platform.referrals.models import ReferralProvider


class ChildForm(forms.ModelForm):
    """Family-facing "add a child" form — just the basics needed to identify a
    child and open a referral. Care schedule / school stay with coordinators and
    ingestion for now (Task 09 follow-up), so they are deliberately left off.
    """

    class Meta:
        model = Child
        fields = [
            "first_name",
            "last_name",
            "date_of_birth",
            "relationship",
            "in_school",
        ]
        widgets = {
            # A native date picker; the model field already stores a real date.
            "date_of_birth": forms.DateInput(
                attrs={"type": "date"},
                format="%Y-%m-%d",
            ),
        }

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # The model allows a blank name, but a child the family adds needs one.
        self.fields["first_name"].required = True


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
