"""URL configuration for the referrals app.

Mounted at ``/referrals/`` in ``config/urls.py``. Coordinator (back-office)
views live under the ``staff/`` prefix (Tasks 04-06); family (front-office)
views live at the app root (Tasks 08-09).
"""

from django.urls import path

from open_child_care_referral_platform.referrals.views import family_add_provider_view
from open_child_care_referral_platform.referrals.views import (
    family_provider_search_view,
)
from open_child_care_referral_platform.referrals.views import family_request_help_view
from open_child_care_referral_platform.referrals.views import my_referrals_view
from open_child_care_referral_platform.referrals.views import portal_view
from open_child_care_referral_platform.referrals.views import referral_add_provider_view
from open_child_care_referral_platform.referrals.views import referral_claim_view
from open_child_care_referral_platform.referrals.views import referral_detail_view
from open_child_care_referral_platform.referrals.views import referral_edit_notes_view
from open_child_care_referral_platform.referrals.views import referral_ingest_view
from open_child_care_referral_platform.referrals.views import (
    referral_invite_family_view,
)
from open_child_care_referral_platform.referrals.views import (
    referral_provider_remove_view,
)
from open_child_care_referral_platform.referrals.views import (
    referral_provider_search_view,
)
from open_child_care_referral_platform.referrals.views import (
    referral_provider_update_view,
)
from open_child_care_referral_platform.referrals.views import referral_queue_view
from open_child_care_referral_platform.referrals.views import referral_set_status_view

app_name = "referrals"
urlpatterns = [
    # Family front office (portal + saved providers) at the app root.
    path("", portal_view, name="portal"),
    path("my/", my_referrals_view, name="my_referrals"),
    path(
        "my/child/<int:child_pk>/search/",
        family_provider_search_view,
        name="family_search",
    ),
    path(
        "my/child/<int:child_pk>/add/<int:provider_pk>/",
        family_add_provider_view,
        name="family_add_provider",
    ),
    path(
        "my/referral/<int:referral_pk>/request-help/",
        family_request_help_view,
        name="request_help",
    ),
    path("staff/", referral_queue_view, name="queue"),
    path("staff/<int:pk>/", referral_detail_view, name="detail"),
    path("staff/<int:pk>/claim/", referral_claim_view, name="claim"),
    path("staff/<int:pk>/status/", referral_set_status_view, name="set_status"),
    path("staff/<int:pk>/notes/", referral_edit_notes_view, name="edit_notes"),
    path(
        "staff/<int:pk>/invite/",
        referral_invite_family_view,
        name="invite_family",
    ),
    path(
        "staff/saved-provider/<int:pk>/remove/",
        referral_provider_remove_view,
        name="provider_remove",
    ),
    path(
        "staff/saved-provider/<int:pk>/update/",
        referral_provider_update_view,
        name="provider_update",
    ),
    path(
        "staff/<int:pk>/search/",
        referral_provider_search_view,
        name="provider_search",
    ),
    path(
        "staff/<int:pk>/add/<int:provider_pk>/",
        referral_add_provider_view,
        name="add_provider",
    ),
    # Server-to-server ingestion (token-authed; outside the staff/ session tree).
    path("ingest/", referral_ingest_view, name="ingest"),
    # family views (Task 09) added later
]
