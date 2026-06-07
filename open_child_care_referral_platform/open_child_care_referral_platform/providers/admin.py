from django.contrib import admin

from open_child_care_referral_platform.providers.models import Inspection
from open_child_care_referral_platform.providers.models import Provider


@admin.register(Provider)
class ProviderAdmin(admin.ModelAdmin):
    list_display = ("id", "provider_name", "source_state", "status", "license_number")
    list_filter = ("source_state",)
    search_fields = ("provider_name", "license_number", "provider_url")


@admin.register(Inspection)
class InspectionAdmin(admin.ModelAdmin):
    list_display = ("id", "provider", "type", "date")
    search_fields = ("provider__provider_name",)
