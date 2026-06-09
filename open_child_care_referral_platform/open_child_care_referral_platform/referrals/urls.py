"""URL configuration for the referrals app.

Mounted at ``/referrals/`` in ``config/urls.py``. Coordinator (back-office)
views live under the ``staff/`` prefix (Tasks 04-06); family (front-office)
views live at the app root (Tasks 08-09).
"""

from django.urls import path

from open_child_care_referral_platform.referrals.views import referral_queue_view

app_name = "referrals"
urlpatterns = [
    path("staff/", referral_queue_view, name="queue"),
    # detail/actions (Task 05), search (Task 06), family views (Task 09) added later
]
