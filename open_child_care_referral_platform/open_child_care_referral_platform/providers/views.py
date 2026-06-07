from typing import Any

from django.views.generic import DetailView
from django.views.generic import ListView

from open_child_care_referral_platform.providers.models import Provider

# Columns shown in the detail page header / metadata footer (or rendered in their
# own section), so they are excluded from the generic "Details" table.
_NON_TABLE_FIELDS = frozenset(
    {
        "id",
        "created",
        "modified",
        "state_data",
        "provider_name",
        "provider_type",
        "status",
        "source_state",
    },
)


class ProviderListView(ListView):
    model = Provider
    context_object_name = "providers"
    paginate_by = 24
    ordering = ["provider_name"]


provider_list_view = ProviderListView.as_view()


class ProviderDetailView(DetailView):
    model = Provider
    context_object_name = "provider"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        provider = self.object
        context["core_fields"] = [
            (field.verbose_name, getattr(provider, field.name))
            for field in provider._meta.concrete_fields  # noqa: SLF001
            if field.name not in _NON_TABLE_FIELDS
        ]
        context["inspections"] = provider.inspections.all()
        return context


provider_detail_view = ProviderDetailView.as_view()
