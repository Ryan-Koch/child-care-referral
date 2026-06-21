from __future__ import annotations

import re
from functools import cached_property
from typing import TYPE_CHECKING
from typing import Any

from django.contrib.postgres.search import TrigramWordSimilarity
from django.db.models import DateField
from django.db.models import F
from django.db.models import Func
from django.db.models import IntegerField
from django.db.models import Q
from django.db.models import Value
from django.db.models.functions import Cast
from django.db.models.functions import Replace
from django.shortcuts import redirect
from django.utils import timezone
from django.views.generic import DetailView
from django.views.generic import ListView

from open_child_care_referral_platform.providers import detail
from open_child_care_referral_platform.providers.models import Provider
from open_child_care_referral_platform.providers.status import status_bucket
from open_child_care_referral_platform.users.http import is_safe_next
from open_child_care_referral_platform.users.roles import FAMILY_GROUP
from open_child_care_referral_platform.users.roles import user_in_group

if TYPE_CHECKING:
    from collections.abc import Iterable

    from django.db.models import QuerySet
    from django.http import HttpRequest
    from django.http import HttpResponseBase

SOUTH_CAROLINA = "South Carolina"

# South Carolina ABC quality ratings, best to worst, then Pending and Exempt.
# This order is meaningful (a quality gradient), so the filter offers the values
# in this sequence rather than sorted alphabetically.
SC_ABC_RATINGS = ("A+", "A", "B+", "B", "C", "P", "E")
SC_RATING_FIELD = "state_data__sc_abc_quality_rating"
SC_PROGRAM_FIELD = "state_data__sc_program_participation"

NEW_YORK = "NY"
NY_REGION_FIELD = "state_data__ny_region_code"
NY_DISTRICT_FIELD = "state_data__ny_school_district_name"
# Child age-group capacity columns, each offered as a "serves this age" filter
# (capacity > 0). (field, label) pairs; only surfaced when New York is selected.
NY_AGE_BUCKETS = (
    ("infant", "Infant"),
    ("toddler", "Toddler"),
    ("preschool", "Preschool"),
    ("school", "School-age"),
)

VIRGINIA = "VA"
# Virginia quality ratings, best to worst. This order is a meaningful gradient
# (like SC's ABC), so the filter offers the values in this sequence.
VA_QUALITY_RATINGS = ("Exceeds Expectations", "Meets Expectations", "Needs Support")
VA_QUALITY_FIELD = "state_data__va_quality_rating"
# Public-funding programs are stored as a single ';'-delimited string (not a JSON
# array), so options are split out and matches are made on delimited tokens.
VA_FUNDING_FIELD = "state_data__va_public_funding"

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


# Scraped numeric text may carry thousands separators ("1,100"), so the regex
# admits only digits/commas/whitespace and commas are stripped before the integer
# cast — that keeps the cast from erroring on genuinely non-numeric values.
_POSITIVE_INT_RE = r"^\s*\d[\d,]*\s*$"


def _filter_positive(queryset: QuerySet[Provider], field: str) -> QuerySet[Provider]:
    """Keep rows whose raw-text ``field`` parses to an integer greater than zero."""
    annotation = f"{field}_positive"
    return (
        queryset.filter(**{f"{field}__regex": _POSITIVE_INT_RE})
        .annotate(
            **{
                annotation: Cast(
                    Replace(F(field), Value(","), Value("")),
                    output_field=IntegerField(),
                ),
            },
        )
        .filter(**{f"{annotation}__gt": 0})
    )


def _delimited_token_regex(token: str) -> str:
    """Regex matching ``token`` as a whole ``;``-delimited element of a string.

    Matching the delimiter boundaries avoids substring false positives (e.g.
    selecting "Head Start" must not also match "Early Head Start"). The token is
    escaped because some carry regex metacharacters, e.g. "...(MCCYN)".
    """
    return rf"(^|;\s*){re.escape(token)}(\s*;|$)"


# Valid WGS84 ranges; scraped coordinates outside them are treated as junk and
# dropped rather than placed at (0, 0) or off the globe.
_LAT_RANGE = (-90.0, 90.0)
_LNG_RANGE = (-180.0, 180.0)


def _parse_coord(value: str | None, low: float, high: float) -> float | None:
    """Parse a raw-text coordinate to a float in ``[low, high]``, else ``None``."""
    try:
        coord = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return coord if low <= coord <= high else None


class ProviderListView(ListView):
    model = Provider
    context_object_name = "providers"
    paginate_by = 24
    ordering = ["provider_name"]

    # Opt-IN, so it fails safe: only the generic catalog binding turns this on
    # (see ``provider_list_view`` below). Every subclass — and any future one —
    # defaults to *not* redirecting, so it can never accidentally bounce a family
    # away from a page that isn't the save-less catalog.
    redirect_family_to_search = False

    def dispatch(
        self,
        request: HttpRequest,
        *args: Any,
        **kwargs: Any,
    ) -> HttpResponseBase:
        if self.redirect_family_to_search and user_in_group(request.user, FAMILY_GROUP):
            # Families have their own save-enabled search (Task 12); steer them
            # off the save-less catalog. Soft, one-way coupling: providers
            # reverses a referrals: URL name.
            return redirect("referrals:family_search")
        return super().dispatch(request, *args, **kwargs)

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
    def selected_ny_region(self) -> str:
        return self.request.GET.get("ny_region", "")

    @cached_property
    def selected_ny_district(self) -> str:
        return self.request.GET.get("ny_district", "")

    @cached_property
    def selected_ny_ages(self) -> list[str]:
        # Multi-select age-group capacity filters, meaningful only for New York.
        if self.selected_state != NEW_YORK:
            return []
        chosen = self.request.GET.getlist("ny_age")
        return [field for field, _label in NY_AGE_BUCKETS if field in chosen]

    @cached_property
    def has_capacity(self) -> bool:
        return self.request.GET.get("has_capacity") == "1"

    @cached_property
    def selected_va_quality(self) -> str:
        return self.request.GET.get("va_quality", "")

    @cached_property
    def selected_va_funding(self) -> list[str]:
        # Multi-select: keep only valid programs, in canonical (sorted) order.
        chosen = self.request.GET.getlist("va_funding")
        return [funding for funding in self.va_fundings if funding in chosen]

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

    @cached_property
    def ny_regions(self) -> list[str]:
        # State-specific filter: only offered for New York.
        if self.selected_state != NEW_YORK:
            return []
        return _distinct_values(self._state_providers, NY_REGION_FIELD)

    @cached_property
    def ny_districts(self) -> list[str]:
        # State-specific filter: only offered for New York.
        if self.selected_state != NEW_YORK:
            return []
        return _distinct_values(self._state_providers, NY_DISTRICT_FIELD)

    @cached_property
    def ny_age_buckets(self) -> list[tuple[str, str]]:
        # (field, label) pairs the template renders as checkboxes; New York only.
        return list(NY_AGE_BUCKETS) if self.selected_state == NEW_YORK else []

    @cached_property
    def va_quality_ratings(self) -> list[str]:
        # State-specific filter: only offered for Virginia, in the canonical
        # quality order, limited to ratings present in the data.
        if self.selected_state != VIRGINIA:
            return []
        present = set(
            self._state_providers.values_list(VA_QUALITY_FIELD, flat=True).distinct(),
        )
        return [rating for rating in VA_QUALITY_RATINGS if rating in present]

    @cached_property
    def va_fundings(self) -> list[str]:
        # State-specific filter. va_public_funding is a ';'-delimited string, so
        # the distinct program names are gathered by splitting and flattening.
        if self.selected_state != VIRGINIA:
            return []
        values = self._state_providers.values_list(VA_FUNDING_FIELD, flat=True)
        fundings: set[str] = set()
        for value in values:
            if value:
                fundings.update(
                    token.strip() for token in value.split(";") if token.strip()
                )
        return sorted(fundings)

    def get_queryset(self) -> QuerySet[Provider]:
        queryset = super().get_queryset()
        if self.selected_state:
            queryset = queryset.filter(source_state=self.selected_state)
            queryset = self._apply_state_filters(queryset)
        if self.selected_license_number:
            queryset = queryset.filter(
                license_number__icontains=self.selected_license_number,
            )
        if self.has_capacity:
            queryset = _filter_positive(queryset, "capacity")
        if self.active_only:
            queryset = self._filter_active(queryset)
        if self.search_query:
            queryset = self._search_by_name(queryset)
        return queryset

    def _apply_state_filters(self, queryset: QuerySet[Provider]) -> QuerySet[Provider]:
        # Filters scoped to the chosen state. Each guards on the state's valid
        # options so stale values left over from another state are ignored.
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
        if self.selected_ny_region in self.ny_regions:
            queryset = queryset.filter(**{NY_REGION_FIELD: self.selected_ny_region})
        if self.selected_ny_district in self.ny_districts:
            queryset = queryset.filter(**{NY_DISTRICT_FIELD: self.selected_ny_district})
        # Each selected age group must have capacity > 0 (AND semantics).
        for field in self.selected_ny_ages:
            queryset = _filter_positive(queryset, field)
        return self._apply_va_filters(queryset)

    def _apply_va_filters(self, queryset: QuerySet[Provider]) -> QuerySet[Provider]:
        if self.selected_va_quality in self.va_quality_ratings:
            queryset = queryset.filter(**{VA_QUALITY_FIELD: self.selected_va_quality})
        # Each selected funding program must appear as a delimited token (AND).
        for funding in self.selected_va_funding:
            queryset = queryset.filter(
                **{f"{VA_FUNDING_FIELD}__regex": _delimited_token_regex(funding)},
            )
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
        context["ny_regions"] = self.ny_regions
        context["ny_districts"] = self.ny_districts
        context["ny_age_buckets"] = self.ny_age_buckets
        context["va_quality_ratings"] = self.va_quality_ratings
        context["va_fundings"] = self.va_fundings
        context["selected_state"] = self.selected_state
        context["selected_county"] = self.selected_county
        context["selected_provider_type"] = self.selected_provider_type
        context["selected_sc_rating"] = self.selected_sc_rating
        context["selected_sc_programs"] = self.selected_sc_programs
        context["selected_ny_region"] = self.selected_ny_region
        context["selected_ny_district"] = self.selected_ny_district
        context["selected_ny_ages"] = self.selected_ny_ages
        context["has_capacity"] = self.has_capacity
        context["selected_va_quality"] = self.selected_va_quality
        context["selected_va_funding"] = self.selected_va_funding
        context["selected_license_number"] = self.selected_license_number
        context["active_only"] = self.active_only
        context["search_query"] = self.search_query
        # Markers for the Compass map pane: the current page's providers that
        # carry usable coordinates. Serialised to JSON in the template.
        context["map_points"] = self._map_points(context["providers"])
        return context

    def _map_points(self, providers: Iterable[Provider]) -> list[dict[str, Any]]:
        points: list[dict[str, Any]] = []
        for provider in providers:
            lat = _parse_coord(provider.latitude, *_LAT_RANGE)
            lng = _parse_coord(provider.longitude, *_LNG_RANGE)
            if lat is None or lng is None:
                continue
            # Some states store "0"/"0" as a placeholder for "no coordinate";
            # drop that "null island" point rather than plotting off Africa.
            if lat == 0 and lng == 0:
                continue
            points.append(
                {
                    "pk": provider.pk,
                    "name": provider.provider_name or "Unnamed provider",
                    "lat": lat,
                    "lng": lng,
                    "bucket": status_bucket(provider.status),
                    "url": provider.get_absolute_url(),
                },
            )
        return points


# The one place the family redirect is enabled — this binding *is* the generic
# save-less catalog at ``providers:list``.
provider_list_view = ProviderListView.as_view(redirect_family_to_search=True)


class ProviderDetailView(DetailView):
    model = Provider
    context_object_name = "provider"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        provider = self.object
        inspections = list(provider.inspections.all())
        compliance = detail.compliance_summary(provider, inspections)
        context["state_profile"] = detail.state_profile(provider)
        context["quality"] = detail.quality_summary(provider)
        context["compliance"] = compliance
        context["show_compliance"] = compliance is not None
        context["glance"] = detail.at_a_glance(provider)
        context["age_groups"] = detail.age_groups(provider)
        context["features"] = detail.program_features(provider)
        context["program_facts"] = detail.program_facts(provider)
        context["contacts"] = detail.contact_rows(provider)
        context["license_rows"] = detail.license_rows(provider)
        context["map_point"] = self._map_point(provider)
        context["back_url"] = self._safe_back_url()
        return context

    def _map_point(self, provider: Provider) -> dict[str, Any] | None:
        """Single Leaflet marker for the sidebar map, or ``None`` if uncoordinated."""
        lat = _parse_coord(provider.latitude, *_LAT_RANGE)
        lng = _parse_coord(provider.longitude, *_LNG_RANGE)
        if lat is None or lng is None or (lat == 0 and lng == 0):
            return None
        return {
            "lat": lat,
            "lng": lng,
            "name": provider.provider_name or "Unnamed provider",
            "bucket": status_bucket(provider.status),
        }

    def _safe_back_url(self) -> str:
        """A ``?next=`` URL to offer as a "back" link, only if same-site safe.

        Lets callers (e.g. the family/coordinator provider search) send a user
        into this shared detail page and back to where they came from, without
        coupling this app to theirs.
        """
        next_url = self.request.GET.get("next", "")
        return next_url if is_safe_next(self.request, next_url) else ""


provider_detail_view = ProviderDetailView.as_view()
