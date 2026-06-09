"""Referrals views.

Task 04 adds the coordinator referral queue. Further coordinator views
(detail/actions, search-to-save) land in Tasks 05-06; family views in Tasks 08-09.
"""

from __future__ import annotations

from functools import cached_property
from typing import TYPE_CHECKING
from typing import Any

from django.views.generic import ListView

from open_child_care_referral_platform.referrals.models import Referral
from open_child_care_referral_platform.users.mixins import CoordinatorRequiredMixin

if TYPE_CHECKING:
    from django.db.models import QuerySet

# Live, actionable work — the queue's default view when no status is chosen.
ACTIVE_STATUSES = (
    Referral.Status.NEW,
    Referral.Status.ASSIGNED,
    Referral.Status.IN_PROGRESS,
)


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
        )
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
