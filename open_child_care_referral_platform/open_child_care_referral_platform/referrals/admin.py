from django.contrib import admin

from open_child_care_referral_platform.referrals.models import Child
from open_child_care_referral_platform.referrals.models import Message
from open_child_care_referral_platform.referrals.models import Referral
from open_child_care_referral_platform.referrals.models import ReferralProvider
from open_child_care_referral_platform.referrals.models import School


class SchoolInline(admin.StackedInline):
    model = School
    extra = 0
    raw_id_fields = ("child",)


@admin.register(Child)
class ChildAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "first_name",
        "last_name",
        "family",
        "referral_need",
        "in_school",
    )
    list_filter = ("relationship", "referral_need", "in_school")
    search_fields = ("first_name", "last_name", "family__email")
    raw_id_fields = ("family", "active_provider")
    inlines = (SchoolInline,)


@admin.register(School)
class SchoolAdmin(admin.ModelAdmin):
    list_display = ("id", "institution_name", "child", "grade_level")
    search_fields = ("institution_name",)
    raw_id_fields = ("child",)


class ReferralProviderInline(admin.TabularInline):
    model = ReferralProvider
    extra = 0
    raw_id_fields = ("provider", "added_by")


@admin.register(Referral)
class ReferralAdmin(admin.ModelAdmin):
    list_display = ("id", "child", "coordinator", "status", "source", "help_requested")
    list_filter = ("status", "source", "help_requested")
    search_fields = ("child__first_name", "child__last_name", "external_id")
    raw_id_fields = ("child", "coordinator")
    inlines = (ReferralProviderInline,)


@admin.register(ReferralProvider)
class ReferralProviderAdmin(admin.ModelAdmin):
    list_display = ("id", "referral", "provider", "status", "added_by")
    list_filter = ("status",)
    raw_id_fields = ("referral", "provider", "added_by")


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("id", "referral", "sender", "created", "read_at")
    list_filter = ("read_at",)
    search_fields = ("body", "sender__email")
    raw_id_fields = ("referral", "sender")
