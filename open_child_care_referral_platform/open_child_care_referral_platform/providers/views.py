from __future__ import annotations

from functools import cached_property
from typing import TYPE_CHECKING
from typing import Any

from django.views.generic import DetailView
from django.views.generic import ListView

from open_child_care_referral_platform.providers.models import Provider

if TYPE_CHECKING:
    from django.db.models import QuerySet

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


def _distinct_values(queryset: QuerySet[Provider], field: str) -> list[str]:
    """Sorted, non-empty distinct values of ``field`` across ``queryset``."""
    return list(
        queryset.exclude(**{f"{field}__isnull": True})
        .exclude(**{field: ""})
        .order_by(field)
        .values_list(field, flat=True)
        .distinct(),
    )


class ProviderListView(ListView):
    model = Provider
    context_object_name = "providers"
    paginate_by = 24
    ordering = ["provider_name"]

    @cached_property
    def selected_state(self) -> str:
        return self.request.GET.get("state", "")

    @cached_property
    def selected_county(self) -> str:
        return self.request.GET.get("county", "")

    @cached_property
    def states(self) -> list[str]:
        return _distinct_values(Provider.objects.all(), "source_state")

    @cached_property
    def counties(self) -> list[str]:
        # Counties only make sense once a state is chosen.
        if not self.selected_state:
            return []
        in_state = Provider.objects.filter(source_state=self.selected_state)
        return _distinct_values(in_state, "county")

    def get_queryset(self) -> QuerySet[Provider]:
        queryset = super().get_queryset()
        if self.selected_state:
            queryset = queryset.filter(source_state=self.selected_state)
            # Ignore a stale county that does not belong to the chosen state.
            if self.selected_county in self.counties:
                queryset = queryset.filter(county=self.selected_county)
        return queryset

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["states"] = self.states
        context["counties"] = self.counties
        context["selected_state"] = self.selected_state
        context["selected_county"] = self.selected_county
        return context


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
