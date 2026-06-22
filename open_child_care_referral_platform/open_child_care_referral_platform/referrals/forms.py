from django import forms
from django.forms import inlineformset_factory

from open_child_care_referral_platform.referrals.models import Child
from open_child_care_referral_platform.referrals.models import Message
from open_child_care_referral_platform.referrals.models import Referral
from open_child_care_referral_platform.referrals.models import ReferralProvider
from open_child_care_referral_platform.referrals.models import School


class ChildForm(forms.ModelForm):
    """Family-facing add/edit-a-child form (the "Family Portal" child form).

    Covers the child's identity and what help the family needs. The weekly care
    schedule is parsed from the POST body in the view (it isn't a single model
    field), and schools come from :data:`SchoolFormSet`.
    """

    class Meta:
        model = Child
        fields = [
            "first_name",
            "last_name",
            "date_of_birth",
            "relationship",
            "referral_need",
            "in_school",
        ]
        widgets = {
            "first_name": forms.TextInput(
                attrs={"class": "fp-input", "placeholder": "e.g. Sofia"},
            ),
            "last_name": forms.TextInput(
                attrs={"class": "fp-input", "placeholder": "Optional"},
            ),
            # A native date picker; the model field already stores a real date.
            "date_of_birth": forms.DateInput(
                attrs={"class": "fp-input", "type": "date"},
                format="%Y-%m-%d",
            ),
            "relationship": forms.Select(attrs={"class": "fp-select"}),
            "referral_need": forms.Select(attrs={"class": "fp-select"}),
            "in_school": forms.CheckboxInput(attrs={"class": "fp-cb"}),
        }

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # The model allows a blank name, but a child the family adds needs one.
        self.fields["first_name"].required = True


# Schools attached to a child, edited inline on the child form. ``extra=3`` gives
# a few blank slots; the form's JS hides the spare ones behind an "Add a school"
# button, and without JS they are just empty rows Django ignores on save.
SchoolFormSet = inlineformset_factory(
    Child,
    School,
    fields=[
        "institution_name",
        "city",
        "state",
        "grade_level",
        "school_year_start",
        "school_year_end",
    ],
    extra=3,
    can_delete=True,
    widgets={
        "institution_name": forms.TextInput(
            attrs={"class": "fp-input", "placeholder": "e.g. Lincoln Elementary"},
        ),
        "city": forms.TextInput(
            attrs={"class": "fp-input", "placeholder": "Columbus"},
        ),
        "state": forms.TextInput(
            attrs={"class": "fp-input", "placeholder": "OH"},
        ),
        "grade_level": forms.TextInput(
            attrs={"class": "fp-input", "placeholder": "K"},
        ),
        "school_year_start": forms.DateInput(
            attrs={"class": "fp-input", "type": "date"},
            format="%Y-%m-%d",
        ),
        "school_year_end": forms.DateInput(
            attrs={"class": "fp-input", "type": "date"},
            format="%Y-%m-%d",
        ),
    },
)


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
