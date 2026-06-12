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

from django.conf import settings
from django.contrib import messages
from django.db.models import Count
from django.db.models import F
from django.db.models import Prefetch
from django.db.models import Q
from django.http import JsonResponse
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
from open_child_care_referral_platform.referrals.forms import MessageForm
from open_child_care_referral_platform.referrals.forms import ReferralNotesForm
from open_child_care_referral_platform.referrals.forms import ReferralProviderForm
from open_child_care_referral_platform.referrals.models import Child
from open_child_care_referral_platform.referrals.models import Message
from open_child_care_referral_platform.referrals.models import Referral
from open_child_care_referral_platform.referrals.models import ReferralProvider
from open_child_care_referral_platform.referrals.services import ingest_referral_request
from open_child_care_referral_platform.users.claims import send_account_claim_email
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


def family_children(user) -> QuerySet[Child]:
    """Children owned by ``user`` — the basis for family ownership scoping."""
    return Child.objects.filter(family=user)


def family_referrals(user) -> QuerySet[Referral]:
    """Referrals for ``user``'s children."""
    return Referral.objects.filter(child__family=user)


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
    def selected_status(self) -> str:
        return self.request.GET.get("status", "")

    @cached_property
    def mine(self) -> bool:
        return self.request.GET.get("mine") == "1"

    @cached_property
    def help_only(self) -> bool:
        return self.request.GET.get("help") == "1"

    def get_queryset(self) -> QuerySet[Referral]:
        queryset = Referral.objects.select_related(
            "child",
            "child__family",
            "coordinator",
        ).annotate(unread_family_messages=_unread_family_messages())
        if self.selected_status in Referral.Status.values:
            queryset = queryset.filter(status=self.selected_status)
        else:
            queryset = queryset.filter(status__in=ACTIVE_STATUSES)
        if self.mine:
            queryset = queryset.filter(coordinator=self.request.user.pk)
        if self.help_only:
            queryset = queryset.filter(help_requested=True)
        # Oldest first: a work queue surfaces the longest-waiting referrals.
        return queryset.order_by("created")

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["status_choices"] = Referral.Status.choices
        context["selected_status"] = self.selected_status
        context["mine"] = self.mine
        context["help_only"] = self.help_only
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
    """Provider search scoped to one of the family's own children."""

    template_name = "referrals/family_provider_search.html"

    @cached_property
    def child(self) -> Child:
        return get_object_or_404(
            family_children(self.request.user),
            pk=self.kwargs["child_pk"],
        )

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["child"] = self.child
        context["saved_provider_ids"] = set(
            ReferralProvider.objects.filter(
                referral__child=self.child,
            ).values_list("provider_id", flat=True),
        )
        context["search_qs"] = self.request.GET.urlencode()
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


@require_POST
@family_required
def family_add_provider_view(
    request: HttpRequest,
    child_pk: int,
    provider_pk: int,
) -> HttpResponse:
    child = get_object_or_404(family_children(request.user), pk=child_pk)
    provider = get_object_or_404(Provider, pk=provider_pk)
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
    messages.success(request, f"Saved {provider}.")
    base = reverse("referrals:family_search", kwargs={"child_pk": child_pk})
    next_qs = request.POST.get("next_qs", "")
    return redirect(f"{base}?{next_qs}" if next_qs else base)


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
