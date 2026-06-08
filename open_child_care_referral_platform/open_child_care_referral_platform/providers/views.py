from __future__ import annotations

from functools import cached_property
from typing import TYPE_CHECKING
from typing import Any

from django.contrib.postgres.search import TrigramWordSimilarity
from django.db.models import DateField
from django.db.models import F
from django.db.models import Func
from django.db.models import Q
from django.db.models import Value
from django.utils import timezone
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

SOUTH_CAROLINA = "South Carolina"

# South Carolina ABC quality ratings, best to worst, then Pending and Exempt.
# This order is meaningful (a quality gradient), so the filter offers the values
# in this sequence rather than sorted alphabetically.
SC_ABC_RATINGS = ("A+", "A", "B+", "B", "C", "P", "E")
SC_RATING_FIELD = "state_data__sc_abc_quality_rating"
SC_PROGRAM_FIELD = "state_data__sc_program_participation"

# Minimum trigram word-similarity for a provider_name to count as a fuzzy match.
# Lower = more lenient (more typo tolerance, more noise). Exact substrings are
# always included regardless of this threshold.
NAME_SEARCH_THRESHOLD = 0.3


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
    def selected_provider_type(self) -> str:
        return self.request.GET.get("provider_type", "")

    @cached_property
    def selected_sc_rating(self) -> str:
        return self.request.GET.get("sc_rating", "")

    @cached_property
    def selected_sc_programs(self) -> list[str]:
        # Multi-select: keep only valid programs, in canonical (sorted) order.
        chosen = self.request.GET.getlist("sc_program")
        return [program for program in self.sc_programs if program in chosen]

    @cached_property
    def selected_license_number(self) -> str:
        return self.request.GET.get("license_number", "").strip()

    @cached_property
    def active_only(self) -> bool:
        return self.request.GET.get("active") == "1"

    @cached_property
    def search_query(self) -> str:
        return self.request.GET.get("q", "").strip()

    @cached_property
    def _state_providers(self) -> QuerySet[Provider]:
        # Valid only once a state is chosen; callers guard on ``selected_state``.
        return Provider.objects.filter(source_state=self.selected_state)

    @cached_property
    def states(self) -> list[str]:
        return _distinct_values(Provider.objects.all(), "source_state")

    @cached_property
    def counties(self) -> list[str]:
        # Counties only make sense once a state is chosen.
        if not self.selected_state:
            return []
        return _distinct_values(self._state_providers, "county")

    @cached_property
    def provider_types(self) -> list[str]:
        # Provider types are likewise scoped to the chosen state.
        if not self.selected_state:
            return []
        return _distinct_values(self._state_providers, "provider_type")

    @cached_property
    def sc_ratings(self) -> list[str]:
        # State-specific filter: only offered for South Carolina, in the
        # canonical quality order, limited to ratings present in the data.
        if self.selected_state != SOUTH_CAROLINA:
            return []
        present = set(
            self._state_providers.values_list(SC_RATING_FIELD, flat=True).distinct(),
        )
        return [rating for rating in SC_ABC_RATINGS if rating in present]

    @cached_property
    def sc_programs(self) -> list[str]:
        # State-specific filter. ``sc_program_participation`` is a JSON array, so
        # the distinct program names are gathered by flattening those arrays.
        if self.selected_state != SOUTH_CAROLINA:
            return []
        lists = self._state_providers.values_list(SC_PROGRAM_FIELD, flat=True)
        programs: set[str] = set()
        for value in lists:
            if value:
                programs.update(value)
        return sorted(programs)

    def get_queryset(self) -> QuerySet[Provider]:
        queryset = super().get_queryset()
        if self.selected_state:
            queryset = queryset.filter(source_state=self.selected_state)
            # Ignore stale values that do not belong to the chosen state.
            if self.selected_county in self.counties:
                queryset = queryset.filter(county=self.selected_county)
            if self.selected_provider_type in self.provider_types:
                queryset = queryset.filter(provider_type=self.selected_provider_type)
            if self.selected_sc_rating in self.sc_ratings:
                queryset = queryset.filter(**{SC_RATING_FIELD: self.selected_sc_rating})
            if self.selected_sc_programs:
                # Containment with a list is AND: the array must hold them all.
                queryset = queryset.filter(
                    **{f"{SC_PROGRAM_FIELD}__contains": self.selected_sc_programs},
                )
        if self.selected_license_number:
            queryset = queryset.filter(
                license_number__icontains=self.selected_license_number,
            )
        if self.active_only:
            queryset = self._filter_active(queryset)
        if self.search_query:
            queryset = self._search_by_name(queryset)
        return queryset

    def _filter_active(self, queryset: QuerySet[Provider]) -> QuerySet[Provider]:
        # license_expiration is raw scraped text ("M/D/YYYY"); parse it in the
        # database and keep providers whose license has not yet expired. NULLIF
        # guards against blank strings; NULL/unparseable dates drop out.
        expiration_date = Func(
            Func(F("license_expiration"), Value(""), function="NULLIF"),
            Value("FMMM/FMDD/YYYY"),
            function="to_date",
            output_field=DateField(),
        )
        return queryset.annotate(license_expiration_date=expiration_date).filter(
            license_expiration_date__gt=timezone.localdate(),
        )

    def _search_by_name(self, queryset: QuerySet[Provider]) -> QuerySet[Provider]:
        # Fuzzy match on provider_name via pg_trgm word similarity, but always
        # include plain substring hits so exact typing never falls below the
        # similarity threshold. Best matches first.
        return (
            queryset.annotate(
                similarity=TrigramWordSimilarity(self.search_query, "provider_name"),
            )
            .filter(
                Q(provider_name__icontains=self.search_query)
                | Q(similarity__gte=NAME_SEARCH_THRESHOLD),
            )
            .order_by("-similarity", "provider_name")
        )

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["states"] = self.states
        context["counties"] = self.counties
        context["provider_types"] = self.provider_types
        context["sc_ratings"] = self.sc_ratings
        context["sc_programs"] = self.sc_programs
        context["selected_state"] = self.selected_state
        context["selected_county"] = self.selected_county
        context["selected_provider_type"] = self.selected_provider_type
        context["selected_sc_rating"] = self.selected_sc_rating
        context["selected_sc_programs"] = self.selected_sc_programs
        context["selected_license_number"] = self.selected_license_number
        context["active_only"] = self.active_only
        context["search_query"] = self.search_query
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
