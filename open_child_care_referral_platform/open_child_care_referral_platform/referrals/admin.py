from django.contrib import admin

from open_child_care_referral_platform.referrals.models import Child
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
