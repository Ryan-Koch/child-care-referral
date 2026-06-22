"""Referrals views.

Task 04 adds the coordinator referral queue. Further coordinator views
(detail/actions, search-to-save) land in Tasks 05-06; family views in Tasks 08-09.
"""

from __future__ import annotations

import json
import secrets
from functools import cached_property
from http import HTTPStatus
from typing import TYPE_CHECKING
from typing import Any
from urllib.parse import urlsplit
from urllib.parse import urlunsplit

from django.conf import settings
from django.contrib import messages
from django.db import transaction
from django.db.models import Case
from django.db.models import Count
from django.db.models import F
from django.db.models import IntegerField
from django.db.models import Prefetch
from django.db.models import Q
from django.db.models import When
from django.http import Http404
from django.http import JsonResponse
from django.http import QueryDict
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.views.generic import DetailView
from django.views.generic import ListView
from django.views.generic import TemplateView

from open_child_care_referral_platform.providers.models import Provider
from open_child_care_referral_platform.providers.views import ProviderListView
from open_child_care_referral_platform.referrals.forms import ChildForm
from open_child_care_referral_platform.referrals.forms import MessageForm
from open_child_care_referral_platform.referrals.forms import ReferralNotesForm
from open_child_care_referral_platform.referrals.forms import ReferralProviderForm
from open_child_care_referral_platform.referrals.forms import SchoolFormSet
from open_child_care_referral_platform.referrals.models import Child
from open_child_care_referral_platform.referrals.models import Message
from open_child_care_referral_platform.referrals.models import Referral
from open_child_care_referral_platform.referrals.models import ReferralProvider
from open_child_care_referral_platform.referrals.selectors import (
    default_selected_child_id,
)
from open_child_care_referral_platform.referrals.selectors import family_children
from open_child_care_referral_platform.referrals.selectors import family_referrals
from open_child_care_referral_platform.referrals.services import ingest_referral_request
from open_child_care_referral_platform.users.claims import send_account_claim_email
from open_child_care_referral_platform.users.http import is_safe_next
from open_child_care_referral_platform.users.mixins import CoordinatorRequiredMixin
from open_child_care_referral_platform.users.mixins import FamilyRequiredMixin
from open_child_care_referral_platform.users.mixins import coordinator_required
from open_child_care_referral_platform.users.mixins import family_required

if TYPE_CHECKING:
    from django.db.models import QuerySet
    from django.http import HttpRequest
    from django.http import HttpResponse

# Live, actionable work — the queue's default view when no status is chosen.
ACTIVE_STATUSES = (
    Referral.Status.NEW,
    Referral.Status.ASSIGNED,
    Referral.Status.IN_PROGRESS,
)

# Queue sort options (the order the design's "Sort" control offers). "priority"
# is the default: help-requested first, then longest-waiting (oldest).
QUEUE_SORTS = ("priority", "oldest", "newest", "status")
# Sentinel status filter meaning "every status" (vs. "" which means active-only).
ALL_STATUSES = "all"

# A care_schedule range is a [start, end] pair.
_TIME_RANGE_PARTS = 2


def _format_care_schedule(schedule: dict[str, Any]) -> list[tuple[str, list[str]]]:
    """Turn the raw ``care_schedule`` JSON into ``(day, ["07:30-09:00", ...])``
    rows for display. Tolerant of odd values; preserves the stored day order."""
    if not isinstance(schedule, dict):
        return []
    rows: list[tuple[str, list[str]]] = []
    for day, ranges in schedule.items():
        labels: list[str] = []
        for time_range in ranges or []:
            if (
                isinstance(time_range, (list, tuple))
                and len(time_range) == _TIME_RANGE_PARTS
            ):
                start, end = time_range
                labels.append(f"{start}-{end}")
            else:
                labels.append(str(time_range))
        rows.append((str(day), labels))
    return rows


# Age bands mirror the queue's ``referral_extras`` table (infant → school-age);
# duplicated here as a small self-contained helper so the detail page's child
# card can label age without reaching into the queue row view-model.
_DETAIL_AGE_BANDS: tuple[tuple[int, str, str], ...] = (
    (1, "Infant", "bi bi-emoji-smile"),
    (3, "Toddler", "bi bi-emoji-laughing"),
    (5, "Preschool", "bi bi-mortarboard"),
)
_DETAIL_SCHOOL_AGE = ("School-age", "bi bi-backpack")
_MONTHS_PER_YEAR = 12


def _child_age(child: Child) -> dict[str, str]:
    """Band label, icon, and a human age string for the child card.

    Returns a neutral "not on file" band and an empty ``detail`` when the date
    of birth is unknown, so the template can fall back gracefully.
    """
    dob = child.date_of_birth
    if dob is None:
        return {
            "band": "Age not on file",
            "icon": "bi bi-question-circle",
            "detail": "",
        }
    today = timezone.localdate()
    months = (today.year - dob.year) * _MONTHS_PER_YEAR + (today.month - dob.month)
    if today.day < dob.day:
        months -= 1
    months = max(months, 0)
    years = months // _MONTHS_PER_YEAR
    if years < 1:
        detail = f"{months} month{'' if months == 1 else 's'} old"
    else:
        detail = f"{years} year{'' if years == 1 else 's'} old"
    band, icon = _DETAIL_SCHOOL_AGE
    for ceiling, label, band_icon in _DETAIL_AGE_BANDS:
        if years < ceiling:
            band, icon = label, band_icon
            break
    return {"band": band, "icon": icon, "detail": detail}


# --- messaging (Task 10) --------------------------------------------------
#
# A message is "family-sent" when its sender is the referral's child's family;
# anything else on the thread is the coordinator side. The two unread counts are
# mirror images of that rule: the coordinator side cares about unread family
# messages; the family cares about unread coordinator messages.
_FAMILY_SENT = Q(messages__sender=F("child__family"))
_UNREAD = Q(messages__read_at__isnull=True)


def _unread_family_messages() -> Count:
    """Per-referral count of unread messages from the family (coordinator view)."""
    return Count("messages", filter=_UNREAD & _FAMILY_SENT)


def _unread_coordinator_messages() -> Count:
    """Per-referral count of unread messages from the coordinator side (family view)."""
    return Count("messages", filter=_UNREAD & ~_FAMILY_SENT)


def _mark_thread_read(referral: Referral, *, reader_is_family: bool) -> None:
    """Mark the messages the reader is receiving as read.

    The family reads coordinator-sent messages; the coordinator side reads
    family-sent ones. ``referral.child`` must be loaded by the caller.
    """
    unread = referral.messages.filter(read_at__isnull=True)
    family_id = referral.child.family_id
    if reader_is_family:
        unread = unread.exclude(sender_id=family_id)
    else:
        unread = unread.filter(sender_id=family_id)
    unread.update(read_at=timezone.now())


class ReferralQueueView(CoordinatorRequiredMixin, ListView):
    model = Referral
    context_object_name = "referrals"
    template_name = "referrals/referral_queue.html"
    paginate_by = 25

    @cached_property
    def query(self) -> str:
        return self.request.GET.get("q", "").strip()

    @cached_property
    def selected_status(self) -> str:
        return self.request.GET.get("status", "")

    @cached_property
    def mine(self) -> bool:
        return self.request.GET.get("mine") == "1"

    @cached_property
    def help_only(self) -> bool:
        return self.request.GET.get("help") == "1"

    @cached_property
    def unassigned_only(self) -> bool:
        return self.request.GET.get("unassigned") == "1"

    @cached_property
    def sort(self) -> str:
        value = self.request.GET.get("sort", "")
        return value if value in QUEUE_SORTS else "priority"

    def get_queryset(self) -> QuerySet[Referral]:
        queryset = Referral.objects.select_related(
            "child",
            "child__family",
            "coordinator",
        ).annotate(unread_family_messages=_unread_family_messages())
        if self.query:
            queryset = queryset.filter(
                Q(child__first_name__icontains=self.query)
                | Q(child__last_name__icontains=self.query)
                | Q(child__family__name__icontains=self.query)
                | Q(child__family__email__icontains=self.query),
            )
        if self.selected_status in Referral.Status.values:
            queryset = queryset.filter(status=self.selected_status)
        elif self.selected_status != ALL_STATUSES:
            # "" (default) → active only; the "All" segment opts out with ALL_STATUSES.
            queryset = queryset.filter(status__in=ACTIVE_STATUSES)
        if self.mine:
            queryset = queryset.filter(coordinator=self.request.user.pk)
        if self.help_only:
            queryset = queryset.filter(help_requested=True)
        if self.unassigned_only:
            queryset = queryset.filter(coordinator__isnull=True)
        return self._ordered(queryset)

    def _ordered(self, queryset: QuerySet[Referral]) -> QuerySet[Referral]:
        if self.sort == "oldest":
            return queryset.order_by("created")
        if self.sort == "newest":
            return queryset.order_by("-created")
        if self.sort == "status":
            rank = Case(
                *(
                    When(status=value, then=position)
                    for position, value in enumerate(Referral.Status.values)
                ),
                default=len(Referral.Status.values),
                output_field=IntegerField(),
            )
            return queryset.annotate(status_rank=rank).order_by(
                "status_rank",
                "created",
            )
        # "priority" (default): help-requested first, then longest-waiting (oldest).
        return queryset.order_by("-help_requested", "created")

    def _query_with(self, **overrides: str | None) -> str:
        """The current querystring with ``overrides`` applied (a value of ``None``
        drops that key). Resets pagination so a changed filter starts at page 1."""
        params = self.request.GET.copy()
        params.pop("page", None)
        for key, value in overrides.items():
            if value is None:
                params.pop(key, None)
            else:
                params[key] = value
        encoded = params.urlencode()
        return f"?{encoded}" if encoded else self.request.path

    def _stat_tiles(self) -> list[dict[str, Any]]:
        stats = Referral.objects.aggregate(
            help=Count("pk", filter=Q(help_requested=True)),
            active=Count("pk", filter=Q(status__in=ACTIVE_STATUSES)),
            unassigned=Count(
                "pk",
                filter=Q(status__in=ACTIVE_STATUSES, coordinator__isnull=True),
            ),
            in_progress=Count("pk", filter=Q(status=Referral.Status.IN_PROGRESS)),
        )
        in_progress_active = self.selected_status == Referral.Status.IN_PROGRESS
        return [
            {
                "label": "Need attention",
                "value": stats["help"],
                "icon": "bi bi-exclamation-triangle-fill",
                "variant": "danger",
                "active": self.help_only,
                "url": self._query_with(
                    help=None if self.help_only else "1",
                    unassigned=None,
                ),
            },
            {
                "label": "Unassigned",
                "value": stats["unassigned"],
                "icon": "bi bi-person-dash",
                "variant": "warn",
                "active": self.unassigned_only,
                "url": self._query_with(
                    unassigned=None if self.unassigned_only else "1",
                    help=None,
                    status=None,
                ),
            },
            {
                "label": "In progress",
                "value": stats["in_progress"],
                "icon": "bi bi-arrow-repeat",
                "variant": "teal",
                "active": in_progress_active,
                "url": self._query_with(
                    status=None if in_progress_active else Referral.Status.IN_PROGRESS,
                ),
            },
            {
                "label": "Active total",
                "value": stats["active"],
                "icon": "bi bi-collection",
                "variant": "neutral",
                "active": False,
                "url": self._query_with(status=None, help=None, unassigned=None),
            },
        ]

    def _status_segments(self) -> list[dict[str, Any]]:
        status = self.selected_status
        return [
            {
                "label": "Active",
                "url": self._query_with(status=None, unassigned=None),
                "active": status in ("", "active"),
            },
            {
                "label": "New",
                "url": self._query_with(status=Referral.Status.NEW),
                "active": status == Referral.Status.NEW,
            },
            {
                "label": "In progress",
                "url": self._query_with(status=Referral.Status.IN_PROGRESS),
                "active": status == Referral.Status.IN_PROGRESS,
            },
            {
                "label": "Matched",
                "url": self._query_with(status=Referral.Status.COMPLETED),
                "active": status == Referral.Status.COMPLETED,
            },
            {
                "label": "All",
                "url": self._query_with(status=ALL_STATUSES),
                "active": status == ALL_STATUSES,
            },
        ]

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["query"] = self.query
        context["selected_status"] = self.selected_status
        context["mine"] = self.mine
        context["help_only"] = self.help_only
        context["unassigned_only"] = self.unassigned_only
        context["sort"] = self.sort
        context["tiles"] = self._stat_tiles()
        context["status_segments"] = self._status_segments()
        context["mine_url"] = self._query_with(mine=None if self.mine else "1")
        context["total_count"] = Referral.objects.count()
        context["has_filters"] = bool(
            self.query
            or self.selected_status not in ("", "active")
            or self.mine
            or self.help_only
            or self.unassigned_only,
        )
        context["clear_url"] = self.request.path
        return context


referral_queue_view = ReferralQueueView.as_view()


class PortalView(FamilyRequiredMixin, TemplateView):
    """Family front-office landing page. Content filled in by Task 09."""

    template_name = "referrals/portal.html"


portal_view = PortalView.as_view()


class MyReferralsView(FamilyRequiredMixin, TemplateView):
    """The family's own children, referrals, and saved providers (View #2)."""

    template_name = "referrals/my_referrals.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        referrals = Referral.objects.annotate(
            unread_coordinator_messages=_unread_coordinator_messages(),
        ).prefetch_related("saved_providers__provider")
        context["children"] = family_children(self.request.user).prefetch_related(
            Prefetch("referrals", queryset=referrals),
        )
        return context


my_referrals_view = MyReferralsView.as_view()


class FamilyProviderSearchView(FamilyRequiredMixin, ProviderListView):
    """One provider search where the family picks which child to save each result
    for. Reuses all of ``ProviderListView``'s filtering; the per-result "save for
    a child" control is the ``family_save_control`` template tag."""

    template_name = "referrals/family_provider_search.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        user = self.request.user
        children = list(family_children(user))
        context["family_children"] = children
        # One query for the page: which of the family's children already saved
        # each provider shown, so cards can say "Saved for …" without N queries.
        page_provider_ids = [provider.pk for provider in context["providers"]]
        saved_map: dict[int, set[int]] = {}
        rows = ReferralProvider.objects.filter(
            referral__in=family_referrals(user),
            provider_id__in=page_provider_ids,
        ).values_list("provider_id", "referral__child_id")
        for provider_id, child_id in rows:
            saved_map.setdefault(provider_id, set()).add(child_id)
        context["family_saved_map"] = saved_map
        # Page-level values the save control would otherwise recompute per card.
        context["family_selected_child_id"] = default_selected_child_id(
            self.request.GET.get("child", ""),
            children,
        )
        context["family_save_next"] = self.request.get_full_path()
        return context


family_provider_search_view = FamilyProviderSearchView.as_view()


class ReferralDetailView(CoordinatorRequiredMixin, DetailView):
    model = Referral
    context_object_name = "referral"
    template_name = "referrals/referral_detail.html"

    def get_queryset(self) -> QuerySet[Referral]:
        return Referral.objects.select_related(
            "child",
            "child__family",
            "coordinator",
        ).prefetch_related(
            "saved_providers__provider",
            "child__schools",
            Prefetch("messages", queryset=Message.objects.select_related("sender")),
        )

    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        # Render first (so the thread can highlight what's new on this load),
        # then mark the family's messages read for the next visit.
        response = super().get(request, *args, **kwargs)
        _mark_thread_read(self.object, reader_is_family=False)
        return response

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        referral = self.object
        context["care_schedule"] = _format_care_schedule(referral.child.care_schedule)
        context["child_age"] = _child_age(referral.child)
        context["status_choices"] = Referral.Status.choices
        context["provider_status_choices"] = ReferralProvider.Status.choices
        context["thread"] = referral.messages.all()
        context["message_form"] = MessageForm()
        return context


referral_detail_view = ReferralDetailView.as_view()


class ReferralProviderSearchView(CoordinatorRequiredMixin, ProviderListView):
    """Provider search in the context of a referral.

    Reuses all of ``ProviderListView``'s filtering/search; only adds the target
    referral and the set of already-saved providers so the template can offer an
    "Add to referral" control (or mark a provider as already added).
    """

    template_name = "referrals/provider_search.html"

    @cached_property
    def referral(self) -> Referral:
        return get_object_or_404(Referral, pk=self.kwargs["pk"])

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["referral"] = self.referral
        context["saved_provider_ids"] = set(
            self.referral.saved_providers.values_list("provider_id", flat=True),
        )
        # Round-tripped through each Add form so the redirect restores filters/page.
        context["search_qs"] = self.request.GET.urlencode()
        return context


referral_provider_search_view = ReferralProviderSearchView.as_view()


def _detail_redirect(referral_pk: int) -> HttpResponse:
    return redirect("referrals:detail", pk=referral_pk)


@require_POST
@coordinator_required
def referral_claim_view(request: HttpRequest, pk: int) -> HttpResponse:
    referral = get_object_or_404(Referral, pk=pk)
    referral.coordinator_id = request.user.pk
    referral.status = Referral.Status.ASSIGNED
    referral.save(update_fields=["coordinator", "status", "modified"])
    messages.success(request, "Referral assigned to you.")
    return _detail_redirect(pk)


@require_POST
@coordinator_required
def referral_set_status_view(request: HttpRequest, pk: int) -> HttpResponse:
    referral = get_object_or_404(Referral, pk=pk)
    status = request.POST.get("status", "")
    if status in Referral.Status.values:
        referral.status = status
        referral.save(update_fields=["status", "modified"])
        messages.success(request, "Status updated.")
    else:
        messages.error(request, "That status is not recognized.")
    return _detail_redirect(pk)


@require_POST
@coordinator_required
def referral_edit_notes_view(request: HttpRequest, pk: int) -> HttpResponse:
    referral = get_object_or_404(Referral, pk=pk)
    form = ReferralNotesForm(request.POST, instance=referral)
    if form.is_valid():
        form.save()
        messages.success(request, "Notes saved.")
    else:
        messages.error(request, "Could not save notes.")
    return _detail_redirect(pk)


@require_POST
@coordinator_required
def referral_invite_family_view(request: HttpRequest, pk: int) -> HttpResponse:
    referral = get_object_or_404(
        Referral.objects.select_related("child__family"),
        pk=pk,
    )
    family = referral.child.family
    if send_account_claim_email(family, request):
        messages.success(request, f"Sent an account-claim email to {family.email}.")
    else:
        messages.error(request, "Could not send the account-claim email.")
    return _detail_redirect(pk)


@require_POST
@coordinator_required
def referral_provider_remove_view(request: HttpRequest, pk: int) -> HttpResponse:
    saved = get_object_or_404(ReferralProvider, pk=pk)
    referral_pk = saved.referral_id
    saved.delete()
    messages.success(request, "Provider removed from the referral.")
    return _detail_redirect(referral_pk)


@require_POST
@coordinator_required
def referral_provider_update_view(request: HttpRequest, pk: int) -> HttpResponse:
    saved = get_object_or_404(ReferralProvider, pk=pk)
    form = ReferralProviderForm(request.POST, instance=saved)
    if form.is_valid():
        form.save()
        messages.success(request, "Saved provider updated.")
    else:
        messages.error(request, "Could not update the saved provider.")
    return _detail_redirect(saved.referral_id)


@require_POST
@coordinator_required
def referral_add_provider_view(
    request: HttpRequest,
    pk: int,
    provider_pk: int,
) -> HttpResponse:
    referral = get_object_or_404(Referral, pk=pk)
    provider = get_object_or_404(Provider, pk=provider_pk)
    ReferralProvider.objects.get_or_create(
        referral=referral,
        provider=provider,
        defaults={"added_by_id": request.user.pk},
    )
    messages.success(request, f"Added {provider} to the referral.")
    # Return to the search with the same filters/page the coordinator was on.
    base = reverse("referrals:provider_search", kwargs={"pk": pk})
    next_qs = request.POST.get("next_qs", "")
    return redirect(f"{base}?{next_qs}" if next_qs else base)


@require_POST
@coordinator_required
def referral_message_post_view(request: HttpRequest, pk: int) -> HttpResponse:
    """Coordinator posts a message to a referral thread (Task 10, View #5).

    Gated like every other coordinator action on the detail page: any
    coordinator can post (the back office is not scoped per-assignee), which
    also lets staff reply before the referral is claimed.
    """
    referral = get_object_or_404(Referral, pk=pk)
    form = MessageForm(request.POST)
    if form.is_valid():
        message = form.save(commit=False)
        message.referral = referral
        message.sender_id = request.user.pk
        message.save()
        messages.success(request, "Message sent.")
    else:
        messages.error(request, "Your message can't be empty.")
    return redirect(reverse("referrals:detail", kwargs={"pk": pk}) + "#messages")


@csrf_exempt
@require_POST
def referral_ingest_view(request: HttpRequest) -> HttpResponse:
    """Server-to-server ingestion endpoint (token-authenticated, no session)."""
    token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    expected = settings.REFERRAL_INGEST_TOKEN
    # An unset token must reject everything — never an open endpoint by default.
    if not expected or not secrets.compare_digest(token, expected):
        return JsonResponse({"detail": "unauthorized"}, status=HTTPStatus.UNAUTHORIZED)
    try:
        payload = json.loads(request.body)
        referrals = ingest_referral_request(payload)
    except (json.JSONDecodeError, ValueError, KeyError) as exc:
        return JsonResponse({"detail": str(exc)}, status=HTTPStatus.BAD_REQUEST)
    return JsonResponse(
        {"referral_ids": [referral.id for referral in referrals]},
        status=HTTPStatus.CREATED,
    )


# The weekly care-schedule days, in display order. The schedule is built from
# and rendered to the child form by hand (it isn't a single model field); the
# stored shape is {"<weekday>": [["HH:MM", "HH:MM"]]} — one range per kept day.
_SCHEDULE_DAYS: tuple[tuple[str, str], ...] = (
    ("monday", "Monday"),
    ("tuesday", "Tuesday"),
    ("wednesday", "Wednesday"),
    ("thursday", "Thursday"),
    ("friday", "Friday"),
    ("saturday", "Saturday"),
    ("sunday", "Sunday"),
)
_DEFAULT_CARE_FROM = "07:30"
_DEFAULT_CARE_TO = "17:30"


def _parse_care_schedule(post: QueryDict) -> dict[str, list[list[str]]]:
    """Build the stored ``care_schedule`` from the child form's day rows.

    A day is kept only when its checkbox is on and both times are present; each
    kept day stores a single ``[start, end]`` range.
    """
    schedule: dict[str, list[list[str]]] = {}
    for key, _label in _SCHEDULE_DAYS:
        if not post.get(f"sched_{key}"):
            continue
        start = (post.get(f"sched_{key}_from") or "").strip()
        end = (post.get(f"sched_{key}_to") or "").strip()
        if start and end:
            schedule[key] = [[start, end]]
    return schedule


def _schedule_rows_from_schedule(schedule: dict[str, Any]) -> list[dict[str, Any]]:
    """Child-form day rows from a stored ``care_schedule`` (or ``{}``)."""
    rows: list[dict[str, Any]] = []
    for key, label in _SCHEDULE_DAYS:
        ranges = schedule.get(key) if isinstance(schedule, dict) else None
        first = None
        if (
            ranges
            and isinstance(ranges[0], (list, tuple))
            and len(ranges[0]) == _TIME_RANGE_PARTS
        ):
            first = ranges[0]
        rows.append(
            {
                "key": key,
                "label": label,
                "on": first is not None,
                "from": first[0] if first else _DEFAULT_CARE_FROM,
                "to": first[1] if first else _DEFAULT_CARE_TO,
            },
        )
    return rows


def _schedule_rows_from_post(post: QueryDict) -> list[dict[str, Any]]:
    """Day rows reflecting what was just submitted (for re-render after an error)."""
    return [
        {
            "key": key,
            "label": label,
            "on": bool(post.get(f"sched_{key}")),
            "from": post.get(f"sched_{key}_from") or _DEFAULT_CARE_FROM,
            "to": post.get(f"sched_{key}_to") or _DEFAULT_CARE_TO,
        }
        for key, label in _SCHEDULE_DAYS
    ]


def _render_child_form(
    request: HttpRequest,
    form: ChildForm,
    formset: Any,
    *,
    schedule_rows: list[dict[str, Any]],
    is_edit: bool,
) -> HttpResponse:
    context = {
        "form": form,
        "school_formset": formset,
        "schedule_rows": schedule_rows,
        "is_edit": is_edit,
    }
    return render(request, "referrals/family_child_form.html", context)


@family_required
def family_add_child_view(request: HttpRequest) -> HttpResponse:
    """Family adds a child, which opens a referral and lands them on its search.

    The child is always owned by ``request.user``; a posted family id is ignored.
    """
    if request.method == "POST":
        form = ChildForm(request.POST)
        # Validate the schools against the (still unsaved) child, then commit
        # child + schedule + schools together so a bad school can't half-save.
        form.instance.family_id = request.user.pk
        formset = SchoolFormSet(request.POST, instance=form.instance)
        if form.is_valid() and formset.is_valid():
            with transaction.atomic():
                child = form.save(commit=False)
                child.family_id = request.user.pk
                child.care_schedule = _parse_care_schedule(request.POST)
                child.save()
                formset.instance = child
                formset.save()
                Referral.objects.create(
                    child=child,
                    source=Referral.Source.FAMILY,
                    status=Referral.Status.NEW,
                )
            messages.success(request, f"Added {child}.")
            # Land on the provider search with the picker defaulting to the new
            # child (the search is one shared view; child rides in the query).
            return redirect(reverse("referrals:family_search") + f"?child={child.pk}")
        schedule_rows = _schedule_rows_from_post(request.POST)
    else:
        form = ChildForm()
        formset = SchoolFormSet(instance=Child())
        schedule_rows = _schedule_rows_from_schedule({})
    return _render_child_form(
        request,
        form,
        formset,
        schedule_rows=schedule_rows,
        is_edit=False,
    )


@family_required
def family_edit_child_view(request: HttpRequest, pk: int) -> HttpResponse:
    """Family edits one of their own children (identity, care schedule, schools).

    Scoped to the family's children, so editing another family's child is a
    clean 404 — the same ownership discipline as the rest of the portal.
    """
    child = get_object_or_404(family_children(request.user), pk=pk)
    if request.method == "POST":
        form = ChildForm(request.POST, instance=child)
        formset = SchoolFormSet(request.POST, instance=child)
        if form.is_valid() and formset.is_valid():
            with transaction.atomic():
                child = form.save(commit=False)
                child.care_schedule = _parse_care_schedule(request.POST)
                child.save()
                formset.save()
            messages.success(request, f"Updated {child}.")
            return redirect("referrals:my_referrals")
        schedule_rows = _schedule_rows_from_post(request.POST)
    else:
        form = ChildForm(instance=child)
        formset = SchoolFormSet(instance=child)
        schedule_rows = _schedule_rows_from_schedule(child.care_schedule)
    return _render_child_form(
        request,
        form,
        formset,
        schedule_rows=schedule_rows,
        is_edit=True,
    )


def _posted_id(request: HttpRequest, key: str) -> int:
    """An int POST value, or a 404 — POST ids are untrusted (no URL converter
    validates them), so anything ``int()`` rejects (missing, non-numeric, or a
    Unicode digit like "²") is a clean 404, never a 500."""
    try:
        return int(request.POST.get(key, ""))
    except (TypeError, ValueError) as exc:
        raise Http404 from exc


def _family_save_redirect(request: HttpRequest, child: Child) -> str:
    """Where to send the family after a save: back to the page they came from
    (``next``, filters preserved) with the just-saved child kept selected.
    Falls back to the search; an off-site ``next`` is rejected."""
    next_url = request.POST.get("next", "")
    if not is_safe_next(request, next_url):
        next_url = reverse("referrals:family_search")
    # Keep the saved child selected without collapsing multi-value filters
    # (e.g. ?sc_program=a&sc_program=b), so QueryDict rather than a plain dict.
    parts = urlsplit(next_url)
    query = QueryDict(parts.query, mutable=True)
    query["child"] = str(child.pk)
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, query.urlencode(), parts.fragment),
    )


@require_POST
@family_required
def family_save_provider_view(request: HttpRequest) -> HttpResponse:
    """Save a provider to one of the family's own children (Task 12).

    Child and provider come from the POST body so a single search (and the
    provider detail page, Task 13) can target any child. Scoping the child lookup
    to the family makes a cross-family save a clean 404.
    """
    child = get_object_or_404(
        family_children(request.user),
        pk=_posted_id(request, "child"),
    )
    provider = get_object_or_404(Provider, pk=_posted_id(request, "provider"))
    # Add to the child's existing referral, or start a family-created one.
    referral = family_referrals(request.user).filter(child=child).first()
    if referral is None:
        referral = Referral.objects.create(
            child=child,
            source=Referral.Source.FAMILY,
            status=Referral.Status.NEW,
        )
    ReferralProvider.objects.get_or_create(
        referral=referral,
        provider=provider,
        defaults={"added_by_id": request.user.pk},
    )
    messages.success(request, f"Saved {provider} for {child}.")
    return redirect(_family_save_redirect(request, child))


# The two family-meaningful outcomes for a saved provider, keyed by the POST
# value the "I'm interested" / "Not for us" buttons send.
_FAMILY_PROVIDER_RESPONSES = {
    "interested": ReferralProvider.Status.SELECTED,
    "pass": ReferralProvider.Status.DECLINED,
}


@require_POST
@family_required
def family_provider_respond_view(request: HttpRequest, pk: int) -> HttpResponse:
    """Family expresses interest in (or passes on) a saved provider (Goal #2).

    The coordinator side already has this via ``referral_provider_update_view``;
    this is the family equivalent, restricted to the two family-meaningful
    outcomes and scoped to the family's own referrals (a cross-family pk is a
    clean 404, the same ownership discipline as the rest of the portal).
    """
    saved = get_object_or_404(
        ReferralProvider.objects.select_related("provider").filter(
            referral__child__family=request.user,
        ),
        pk=pk,
    )
    status = _FAMILY_PROVIDER_RESPONSES.get(request.POST.get("response", ""))
    if status is None:
        messages.error(request, "That response is not recognized.")
    elif status == ReferralProvider.Status.SELECTED:
        saved.status = status
        saved.save(update_fields=["status", "modified"])
        messages.success(
            request,
            f"Great — we've let your coordinator know you're interested in "
            f"{saved.provider}.",
        )
    else:
        saved.status = status
        saved.save(update_fields=["status", "modified"])
        messages.success(
            request,
            f"Thanks — we'll keep looking beyond {saved.provider}.",
        )
    return redirect("referrals:my_referrals")


@require_POST
@family_required
def family_request_help_view(request: HttpRequest, referral_pk: int) -> HttpResponse:
    referral = get_object_or_404(family_referrals(request.user), pk=referral_pk)
    referral.help_requested = True
    referral.save(update_fields=["help_requested", "modified"])
    messages.success(
        request,
        "We've let a coordinator know you'd like help with this referral.",
    )
    return redirect("referrals:my_referrals")


@family_required
def family_messages_view(request: HttpRequest, referral_pk: int) -> HttpResponse:
    """Family's message thread for one of their referrals (Task 10, View #6).

    Scoped to the family's own referrals — another family's thread is a 404,
    same ownership discipline as the rest of the portal.
    """
    referral = get_object_or_404(
        family_referrals(request.user).select_related("child__family", "coordinator"),
        pk=referral_pk,
    )
    # Read the thread before marking it, so the page can highlight what's new.
    thread = list(referral.messages.select_related("sender"))
    _mark_thread_read(referral, reader_is_family=True)
    context = {
        "referral": referral,
        "thread": thread,
        "message_form": MessageForm(),
    }
    return render(request, "referrals/family_messages.html", context)


@require_POST
@family_required
def family_message_post_view(request: HttpRequest, referral_pk: int) -> HttpResponse:
    referral = get_object_or_404(family_referrals(request.user), pk=referral_pk)
    form = MessageForm(request.POST)
    if form.is_valid():
        message = form.save(commit=False)
        message.referral = referral
        message.sender_id = request.user.pk
        message.save()
        messages.success(request, "Message sent.")
    else:
        messages.error(request, "Your message can't be empty.")
    return redirect("referrals:family_messages", referral_pk=referral_pk)
