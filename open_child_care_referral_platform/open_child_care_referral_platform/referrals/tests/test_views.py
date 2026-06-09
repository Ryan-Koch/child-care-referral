from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest
from django.contrib.auth.models import Group
from django.urls import reverse

from open_child_care_referral_platform.providers.tests.factories import ProviderFactory
from open_child_care_referral_platform.referrals.models import Referral
from open_child_care_referral_platform.referrals.models import ReferralProvider
from open_child_care_referral_platform.referrals.tests.factories import ReferralFactory
from open_child_care_referral_platform.referrals.tests.factories import (
    ReferralProviderFactory,
)
from open_child_care_referral_platform.users.roles import COORDINATOR_GROUP
from open_child_care_referral_platform.users.roles import FAMILY_GROUP
from open_child_care_referral_platform.users.roles import ensure_roles
from open_child_care_referral_platform.users.tests.factories import UserFactory

if TYPE_CHECKING:
    from open_child_care_referral_platform.users.models import User


def make_coordinator() -> User:
    ensure_roles()
    user = UserFactory.create()
    user.groups.add(Group.objects.get(name=COORDINATOR_GROUP))
    return user


def make_family() -> User:
    ensure_roles()
    user = UserFactory.create()
    user.groups.add(Group.objects.get(name=FAMILY_GROUP))
    return user


@pytest.mark.django_db
def test_queue_redirects_anonymous_to_login(client) -> None:
    response = client.get(reverse("referrals:queue"))
    assert response.status_code == HTTPStatus.FOUND


@pytest.mark.django_db
def test_queue_forbids_non_coordinator(client) -> None:
    client.force_login(make_family())
    response = client.get(reverse("referrals:queue"))
    assert response.status_code == HTTPStatus.FORBIDDEN


@pytest.mark.django_db
def test_queue_allows_coordinator(client) -> None:
    client.force_login(make_coordinator())
    response = client.get(reverse("referrals:queue"))
    assert response.status_code == HTTPStatus.OK


@pytest.mark.django_db
def test_queue_defaults_to_active_oldest_first(client) -> None:
    client.force_login(make_coordinator())
    older = ReferralFactory.create(status=Referral.Status.NEW)
    newer = ReferralFactory.create(status=Referral.Status.IN_PROGRESS)
    completed = ReferralFactory.create(status=Referral.Status.COMPLETED)

    response = client.get(reverse("referrals:queue"))
    referrals = list(response.context["referrals"])

    assert completed not in referrals
    assert referrals.index(older) < referrals.index(newer)


@pytest.mark.django_db
def test_queue_status_filter_can_surface_completed(client) -> None:
    client.force_login(make_coordinator())
    active = ReferralFactory.create(status=Referral.Status.NEW)
    completed = ReferralFactory.create(status=Referral.Status.COMPLETED)

    response = client.get(
        reverse("referrals:queue"),
        {"status": Referral.Status.COMPLETED},
    )
    referrals = list(response.context["referrals"])

    assert completed in referrals
    assert active not in referrals


@pytest.mark.django_db
def test_queue_mine_filter(client) -> None:
    coordinator = make_coordinator()
    other = make_coordinator()
    client.force_login(coordinator)
    mine = ReferralFactory.create(
        status=Referral.Status.ASSIGNED,
        coordinator=coordinator,
    )
    theirs = ReferralFactory.create(
        status=Referral.Status.ASSIGNED,
        coordinator=other,
    )

    response = client.get(reverse("referrals:queue"), {"mine": "1"})
    referrals = list(response.context["referrals"])

    assert mine in referrals
    assert theirs not in referrals


@pytest.mark.django_db
def test_queue_help_filter(client) -> None:
    client.force_login(make_coordinator())
    needs_help = ReferralFactory.create(
        status=Referral.Status.NEW,
        help_requested=True,
    )
    normal = ReferralFactory.create(status=Referral.Status.NEW)

    response = client.get(reverse("referrals:queue"), {"help": "1"})
    referrals = list(response.context["referrals"])

    assert needs_help in referrals
    assert normal not in referrals


@pytest.mark.django_db
def test_queue_shows_assignee(client) -> None:
    coordinator = make_coordinator()
    coordinator.name = "Casey Coordinator"
    coordinator.save()
    client.force_login(coordinator)
    ReferralFactory.create(status=Referral.Status.ASSIGNED, coordinator=coordinator)
    unassigned = ReferralFactory.create(status=Referral.Status.NEW)

    content = client.get(reverse("referrals:queue")).content.decode()

    assert "Casey Coordinator" in content
    assert "Unassigned" in content
    assert unassigned.coordinator is None


# --- detail view + actions ------------------------------------------------


def _detail_url(referral: Referral) -> str:
    return reverse("referrals:detail", kwargs={"pk": referral.pk})


@pytest.mark.django_db
def test_detail_forbids_non_coordinator(client) -> None:
    client.force_login(make_family())
    referral = ReferralFactory.create()
    response = client.get(_detail_url(referral))
    assert response.status_code == HTTPStatus.FORBIDDEN


@pytest.mark.django_db
def test_detail_shows_saved_providers(client) -> None:
    client.force_login(make_coordinator())
    saved = ReferralProviderFactory.create()
    response = client.get(_detail_url(saved.referral))
    assert response.status_code == HTTPStatus.OK
    assert str(saved.provider) in response.content.decode()


@pytest.mark.django_db
def test_detail_renders_empty_care_schedule(client) -> None:
    client.force_login(make_coordinator())
    referral = ReferralFactory.create()  # child.care_schedule defaults to {}
    response = client.get(_detail_url(referral))
    assert response.status_code == HTTPStatus.OK


@pytest.mark.django_db
def test_claim_assigns_current_coordinator(client) -> None:
    coordinator = make_coordinator()
    client.force_login(coordinator)
    referral = ReferralFactory.create(status=Referral.Status.NEW)
    client.post(reverse("referrals:claim", kwargs={"pk": referral.pk}))
    referral.refresh_from_db()
    assert referral.coordinator == coordinator
    assert referral.status == Referral.Status.ASSIGNED


@pytest.mark.django_db
def test_claim_requires_post(client) -> None:
    client.force_login(make_coordinator())
    referral = ReferralFactory.create()
    response = client.get(reverse("referrals:claim", kwargs={"pk": referral.pk}))
    assert response.status_code == HTTPStatus.METHOD_NOT_ALLOWED


@pytest.mark.django_db
def test_claim_rejects_non_coordinator(client) -> None:
    client.force_login(make_family())
    referral = ReferralFactory.create()
    response = client.post(reverse("referrals:claim", kwargs={"pk": referral.pk}))
    assert response.status_code == HTTPStatus.FORBIDDEN
    referral.refresh_from_db()
    assert referral.coordinator is None


@pytest.mark.django_db
def test_set_status_updates_valid_and_ignores_invalid(client) -> None:
    client.force_login(make_coordinator())
    referral = ReferralFactory.create(status=Referral.Status.NEW)
    status_url = reverse("referrals:set_status", kwargs={"pk": referral.pk})

    client.post(status_url, {"status": Referral.Status.COMPLETED})
    referral.refresh_from_db()
    assert referral.status == Referral.Status.COMPLETED

    client.post(status_url, {"status": "bogus"})
    referral.refresh_from_db()
    assert referral.status == Referral.Status.COMPLETED


@pytest.mark.django_db
def test_edit_notes_saves(client) -> None:
    client.force_login(make_coordinator())
    referral = ReferralFactory.create()
    client.post(
        reverse("referrals:edit_notes", kwargs={"pk": referral.pk}),
        {"notes": "Called the family today."},
    )
    referral.refresh_from_db()
    assert referral.notes == "Called the family today."


@pytest.mark.django_db
def test_provider_remove_deletes_link(client) -> None:
    client.force_login(make_coordinator())
    saved = ReferralProviderFactory.create()
    client.post(reverse("referrals:provider_remove", kwargs={"pk": saved.pk}))
    assert not ReferralProvider.objects.filter(pk=saved.pk).exists()


@pytest.mark.django_db
def test_provider_update_changes_status_and_notes(client) -> None:
    client.force_login(make_coordinator())
    saved = ReferralProviderFactory.create()
    client.post(
        reverse("referrals:provider_update", kwargs={"pk": saved.pk}),
        {"status": ReferralProvider.Status.SELECTED, "notes": "Top pick."},
    )
    saved.refresh_from_db()
    assert saved.status == ReferralProvider.Status.SELECTED
    assert saved.notes == "Top pick."


# --- provider search-to-save ----------------------------------------------


@pytest.mark.django_db
def test_search_forbids_non_coordinator(client) -> None:
    client.force_login(make_family())
    referral = ReferralFactory.create()
    url = reverse("referrals:provider_search", kwargs={"pk": referral.pk})
    response = client.get(url)
    assert response.status_code == HTTPStatus.FORBIDDEN


@pytest.mark.django_db
def test_search_filters_and_marks_already_saved(client) -> None:
    client.force_login(make_coordinator())
    referral = ReferralFactory.create()
    ohio = ProviderFactory.create(provider_name="Sunshine OH", source_state="OH")
    virginia = ProviderFactory.create(provider_name="Bluebird VA", source_state="VA")
    ReferralProvider.objects.create(referral=referral, provider=ohio)

    url = reverse("referrals:provider_search", kwargs={"pk": referral.pk})
    response = client.get(url, {"state": "OH"})

    providers = list(response.context["providers"])
    assert ohio in providers
    assert virginia not in providers
    assert ohio.id in response.context["saved_provider_ids"]
    assert response.context["referral"] == referral


@pytest.mark.django_db
def test_add_provider_is_idempotent(client) -> None:
    coordinator = make_coordinator()
    client.force_login(coordinator)
    referral = ReferralFactory.create()
    provider = ProviderFactory.create()
    add_url = reverse(
        "referrals:add_provider",
        kwargs={"pk": referral.pk, "provider_pk": provider.pk},
    )

    client.post(add_url, {"next_qs": "state=OH"})
    client.post(add_url, {"next_qs": "state=OH"})

    links = ReferralProvider.objects.filter(referral=referral, provider=provider)
    assert links.count() == 1
    assert links.get().added_by == coordinator


@pytest.mark.django_db
def test_add_provider_redirects_preserving_query(client) -> None:
    client.force_login(make_coordinator())
    referral = ReferralFactory.create()
    provider = ProviderFactory.create()
    add_url = reverse(
        "referrals:add_provider",
        kwargs={"pk": referral.pk, "provider_pk": provider.pk},
    )
    response = client.post(add_url, {"next_qs": "state=OH&page=2"})
    assert response.status_code == HTTPStatus.FOUND
    search_url = reverse("referrals:provider_search", kwargs={"pk": referral.pk})
    assert response.url == f"{search_url}?state=OH&page=2"


@pytest.mark.django_db
def test_add_provider_rejects_non_coordinator(client) -> None:
    client.force_login(make_family())
    referral = ReferralFactory.create()
    provider = ProviderFactory.create()
    add_url = reverse(
        "referrals:add_provider",
        kwargs={"pk": referral.pk, "provider_pk": provider.pk},
    )
    response = client.post(add_url, {"next_qs": ""})
    assert response.status_code == HTTPStatus.FORBIDDEN
    assert not ReferralProvider.objects.filter(
        referral=referral,
        provider=provider,
    ).exists()


@pytest.mark.django_db
def test_search_card_links_to_provider_detail(client) -> None:
    client.force_login(make_coordinator())
    referral = ReferralFactory.create()
    provider = ProviderFactory.create(source_state="OH")
    response = client.get(
        reverse("referrals:provider_search", kwargs={"pk": referral.pk}),
        {"state": "OH"},
    )
    content = response.content.decode()
    assert reverse("providers:detail", kwargs={"pk": provider.pk}) in content
    assert "View details" in content


# --- navigation -----------------------------------------------------------


@pytest.mark.django_db
def test_nav_shows_queue_link_for_coordinator(client) -> None:
    client.force_login(make_coordinator())
    response = client.get(reverse("providers:list"))
    assert reverse("referrals:queue") in response.content.decode()


@pytest.mark.django_db
def test_nav_hides_queue_link_for_family(client) -> None:
    client.force_login(make_family())
    response = client.get(reverse("providers:list"))
    assert reverse("referrals:queue") not in response.content.decode()
