from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest
from django.contrib.auth.models import Group
from django.core import mail
from django.urls import reverse

from open_child_care_referral_platform.providers.tests.factories import ProviderFactory
from open_child_care_referral_platform.referrals.models import Message
from open_child_care_referral_platform.referrals.models import Referral
from open_child_care_referral_platform.referrals.models import ReferralProvider
from open_child_care_referral_platform.referrals.tests.factories import ChildFactory
from open_child_care_referral_platform.referrals.tests.factories import MessageFactory
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
    # "View details" carries a back link to this search (with filters).
    assert "?next=" in content


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


@pytest.mark.django_db
def test_nav_shows_my_providers_link_for_family(client) -> None:
    client.force_login(make_family())
    response = client.get(reverse("providers:list"))
    assert reverse("referrals:my_referrals") in response.content.decode()


@pytest.mark.django_db
def test_nav_hides_my_providers_link_for_coordinator(client) -> None:
    client.force_login(make_coordinator())
    response = client.get(reverse("providers:list"))
    assert reverse("referrals:my_referrals") not in response.content.decode()


# --- family portal + claim invite -----------------------------------------


@pytest.mark.django_db
def test_portal_allows_family(client) -> None:
    client.force_login(make_family())
    response = client.get(reverse("referrals:portal"))
    assert response.status_code == HTTPStatus.OK


@pytest.mark.django_db
def test_portal_forbids_coordinator(client) -> None:
    client.force_login(make_coordinator())
    response = client.get(reverse("referrals:portal"))
    assert response.status_code == HTTPStatus.FORBIDDEN


@pytest.mark.django_db
def test_portal_redirects_anonymous(client) -> None:
    response = client.get(reverse("referrals:portal"))
    assert response.status_code == HTTPStatus.FOUND


@pytest.mark.django_db
def test_invite_family_sends_claim_email(client) -> None:
    client.force_login(make_coordinator())
    referral = ReferralFactory.create()
    referral.child.family.set_unusable_password()
    referral.child.family.save()

    response = client.post(
        reverse("referrals:invite_family", kwargs={"pk": referral.pk}),
    )

    assert response.status_code == HTTPStatus.FOUND
    assert len(mail.outbox) == 1
    assert referral.child.family.email in mail.outbox[0].to


@pytest.mark.django_db
def test_invite_family_rejects_non_coordinator(client) -> None:
    client.force_login(make_family())
    referral = ReferralFactory.create()
    response = client.post(
        reverse("referrals:invite_family", kwargs={"pk": referral.pk}),
    )
    assert response.status_code == HTTPStatus.FORBIDDEN
    assert not mail.outbox


# --- family saved providers (View #2) -------------------------------------


def _family_add_url(child_pk: int, provider_pk: int) -> str:
    return reverse(
        "referrals:family_add_provider",
        kwargs={"child_pk": child_pk, "provider_pk": provider_pk},
    )


@pytest.mark.django_db
def test_my_referrals_shows_only_own_children(client) -> None:
    fam = make_family()
    other = make_family()
    client.force_login(fam)
    ChildFactory.create(family=fam, first_name="Mine", last_name="Kid")
    ChildFactory.create(family=other, first_name="Theirs", last_name="Kid")

    content = client.get(reverse("referrals:my_referrals")).content.decode()

    assert "Mine Kid" in content
    assert "Theirs Kid" not in content


@pytest.mark.django_db
def test_my_referrals_forbids_coordinator(client) -> None:
    client.force_login(make_coordinator())
    response = client.get(reverse("referrals:my_referrals"))
    assert response.status_code == HTTPStatus.FORBIDDEN


@pytest.mark.django_db
def test_family_search_filters_and_marks_saved(client) -> None:
    fam = make_family()
    client.force_login(fam)
    child = ChildFactory.create(family=fam)
    ohio = ProviderFactory.create(provider_name="Sunshine OH", source_state="OH")
    virginia = ProviderFactory.create(provider_name="Bluebird VA", source_state="VA")
    referral = ReferralFactory.create(child=child)
    ReferralProvider.objects.create(referral=referral, provider=ohio)

    url = reverse("referrals:family_search", kwargs={"child_pk": child.pk})
    response = client.get(url, {"state": "OH"})

    providers = list(response.context["providers"])
    assert ohio in providers
    assert virginia not in providers
    assert ohio.id in response.context["saved_provider_ids"]
    assert response.context["child"] == child


@pytest.mark.django_db
def test_family_search_404_for_other_familys_child(client) -> None:
    fam = make_family()
    other = make_family()
    client.force_login(fam)
    other_child = ChildFactory.create(family=other)
    url = reverse("referrals:family_search", kwargs={"child_pk": other_child.pk})
    assert client.get(url).status_code == HTTPStatus.NOT_FOUND


@pytest.mark.django_db
def test_family_add_provider_creates_family_referral(client) -> None:
    fam = make_family()
    client.force_login(fam)
    child = ChildFactory.create(family=fam)  # no referral yet
    provider = ProviderFactory.create()

    response = client.post(
        _family_add_url(child.pk, provider.pk),
        {"next_qs": "state=OH"},
    )

    assert response.status_code == HTTPStatus.FOUND
    referral = Referral.objects.get(child=child)
    assert referral.source == Referral.Source.FAMILY
    link = ReferralProvider.objects.get(referral=referral, provider=provider)
    assert link.added_by == fam


@pytest.mark.django_db
def test_family_add_provider_uses_existing_referral(client) -> None:
    fam = make_family()
    client.force_login(fam)
    child = ChildFactory.create(family=fam)
    existing = ReferralFactory.create(child=child, source=Referral.Source.STAFF)
    provider = ProviderFactory.create()

    client.post(_family_add_url(child.pk, provider.pk), {"next_qs": ""})

    assert Referral.objects.filter(child=child).count() == 1
    assert ReferralProvider.objects.filter(
        referral=existing,
        provider=provider,
    ).exists()


@pytest.mark.django_db
def test_family_add_provider_404_for_other_familys_child(client) -> None:
    fam = make_family()
    other = make_family()
    client.force_login(fam)
    other_child = ChildFactory.create(family=other)
    provider = ProviderFactory.create()

    response = client.post(
        _family_add_url(other_child.pk, provider.pk),
        {"next_qs": ""},
    )

    assert response.status_code == HTTPStatus.NOT_FOUND
    assert not ReferralProvider.objects.filter(provider=provider).exists()


@pytest.mark.django_db
def test_family_add_provider_rejects_coordinator(client) -> None:
    client.force_login(make_coordinator())
    fam = make_family()
    child = ChildFactory.create(family=fam)
    provider = ProviderFactory.create()

    response = client.post(_family_add_url(child.pk, provider.pk), {"next_qs": ""})

    assert response.status_code == HTTPStatus.FORBIDDEN


@pytest.mark.django_db
def test_request_help_flags_and_surfaces_in_queue(client) -> None:
    fam = make_family()
    coordinator = make_coordinator()
    child = ChildFactory.create(family=fam)
    referral = ReferralFactory.create(child=child, status=Referral.Status.NEW)

    client.force_login(fam)
    response = client.post(
        reverse("referrals:request_help", kwargs={"referral_pk": referral.pk}),
    )
    assert response.status_code == HTTPStatus.FOUND
    referral.refresh_from_db()
    assert referral.help_requested is True

    client.force_login(coordinator)
    queue = client.get(reverse("referrals:queue"), {"help": "1"})
    assert referral in list(queue.context["referrals"])


@pytest.mark.django_db
def test_request_help_404_for_other_familys_referral(client) -> None:
    fam = make_family()
    other = make_family()
    client.force_login(fam)
    other_child = ChildFactory.create(family=other)
    referral = ReferralFactory.create(child=other_child)

    response = client.post(
        reverse("referrals:request_help", kwargs={"referral_pk": referral.pk}),
    )

    assert response.status_code == HTTPStatus.NOT_FOUND
    referral.refresh_from_db()
    assert referral.help_requested is False


# --- messaging (Task 10, Views #5/#6) -------------------------------------


def _family_referral():
    """A referral whose child's family is a Family-group user, plus that user."""
    fam = make_family()
    child = ChildFactory.create(family=fam)
    return ReferralFactory.create(child=child), fam


def _family_message(referral) -> Message:
    return MessageFactory.create(referral=referral, sender=referral.child.family)


def _coordinator_message(referral, coordinator=None) -> Message:
    return MessageFactory.create(
        referral=referral,
        sender=coordinator or make_coordinator(),
    )


@pytest.mark.django_db
def test_detail_renders_message_thread(client) -> None:
    client.force_login(make_coordinator())
    referral, _ = _family_referral()
    _family_message(referral)  # body via factory
    message = referral.messages.get()

    content = client.get(_detail_url(referral)).content.decode()

    assert message.body in content


@pytest.mark.django_db
def test_coordinator_message_post_creates_message(client) -> None:
    coordinator = make_coordinator()
    client.force_login(coordinator)
    referral, _ = _family_referral()

    response = client.post(
        reverse("referrals:message_post", kwargs={"pk": referral.pk}),
        {"body": "Following up on your request."},
    )

    assert response.status_code == HTTPStatus.FOUND
    assert response.url.endswith("#messages")
    message = referral.messages.get()
    assert message.sender == coordinator
    assert message.body == "Following up on your request."


@pytest.mark.django_db
def test_coordinator_message_post_rejects_empty_body(client) -> None:
    client.force_login(make_coordinator())
    referral, _ = _family_referral()

    client.post(
        reverse("referrals:message_post", kwargs={"pk": referral.pk}),
        {"body": "   "},
    )

    assert not referral.messages.exists()


@pytest.mark.django_db
def test_coordinator_message_post_rejects_non_coordinator(client) -> None:
    referral, fam = _family_referral()
    client.force_login(fam)

    response = client.post(
        reverse("referrals:message_post", kwargs={"pk": referral.pk}),
        {"body": "hi"},
    )

    assert response.status_code == HTTPStatus.FORBIDDEN
    assert not referral.messages.exists()


@pytest.mark.django_db
def test_detail_view_marks_family_messages_read(client) -> None:
    referral, _ = _family_referral()
    family_msg = _family_message(referral)
    # A coordinator's own message stays untouched (only the *other* side's read).
    coord_msg = _coordinator_message(referral)

    client.force_login(make_coordinator())
    client.get(_detail_url(referral))

    family_msg.refresh_from_db()
    coord_msg.refresh_from_db()
    assert family_msg.read_at is not None
    assert coord_msg.read_at is None


@pytest.mark.django_db
def test_queue_shows_unread_family_message_count(client) -> None:
    referral, _ = _family_referral()
    _family_message(referral)
    referral.status = Referral.Status.NEW
    referral.save(update_fields=["status"])

    client.force_login(make_coordinator())
    response = client.get(reverse("referrals:queue"))

    queued = next(r for r in response.context["referrals"] if r.pk == referral.pk)
    assert queued.unread_family_messages == 1
    assert "1 new" in response.content.decode()


@pytest.mark.django_db
def test_family_messages_page_shows_own_thread(client) -> None:
    referral, fam = _family_referral()
    _coordinator_message(referral)
    message = referral.messages.get()
    client.force_login(fam)

    response = client.get(
        reverse("referrals:family_messages", kwargs={"referral_pk": referral.pk}),
    )

    assert response.status_code == HTTPStatus.OK
    assert message.body in response.content.decode()


@pytest.mark.django_db
def test_family_messages_page_404_for_other_familys_referral(client) -> None:
    referral, _ = _family_referral()
    other = make_family()
    client.force_login(other)

    response = client.get(
        reverse("referrals:family_messages", kwargs={"referral_pk": referral.pk}),
    )

    assert response.status_code == HTTPStatus.NOT_FOUND


@pytest.mark.django_db
def test_family_messages_page_forbids_coordinator(client) -> None:
    referral, _ = _family_referral()
    client.force_login(make_coordinator())

    response = client.get(
        reverse("referrals:family_messages", kwargs={"referral_pk": referral.pk}),
    )

    assert response.status_code == HTTPStatus.FORBIDDEN


@pytest.mark.django_db
def test_family_messages_page_marks_coordinator_messages_read(client) -> None:
    referral, fam = _family_referral()
    coord_msg = _coordinator_message(referral)
    own_msg = _family_message(referral)
    client.force_login(fam)

    client.get(
        reverse("referrals:family_messages", kwargs={"referral_pk": referral.pk}),
    )

    coord_msg.refresh_from_db()
    own_msg.refresh_from_db()
    assert coord_msg.read_at is not None
    assert own_msg.read_at is None


@pytest.mark.django_db
def test_family_message_post_creates_message(client) -> None:
    referral, fam = _family_referral()
    client.force_login(fam)

    response = client.post(
        reverse("referrals:family_message_post", kwargs={"referral_pk": referral.pk}),
        {"body": "Thanks for the help!"},
    )

    assert response.status_code == HTTPStatus.FOUND
    message = referral.messages.get()
    assert message.sender == fam
    assert message.body == "Thanks for the help!"


@pytest.mark.django_db
def test_family_message_post_404_for_other_familys_referral(client) -> None:
    referral, _ = _family_referral()
    other = make_family()
    client.force_login(other)

    response = client.post(
        reverse("referrals:family_message_post", kwargs={"referral_pk": referral.pk}),
        {"body": "sneaky"},
    )

    assert response.status_code == HTTPStatus.NOT_FOUND
    assert not referral.messages.exists()


@pytest.mark.django_db
def test_family_message_post_rejects_coordinator(client) -> None:
    referral, _ = _family_referral()
    client.force_login(make_coordinator())

    response = client.post(
        reverse("referrals:family_message_post", kwargs={"referral_pk": referral.pk}),
        {"body": "hi"},
    )

    assert response.status_code == HTTPStatus.FORBIDDEN
    assert not referral.messages.exists()


@pytest.mark.django_db
def test_my_referrals_shows_unread_coordinator_badge(client) -> None:
    referral, fam = _family_referral()
    _coordinator_message(referral)
    client.force_login(fam)

    response = client.get(reverse("referrals:my_referrals"))

    child = next(c for c in response.context["children"] if c.pk == referral.child.pk)
    annotated = child.referrals.all()[0]
    assert annotated.unread_coordinator_messages == 1


@pytest.mark.django_db
def test_nav_unread_badge_counts_only_coordinator_messages(client) -> None:
    referral, fam = _family_referral()
    _coordinator_message(referral)
    _family_message(referral)  # the family's own message must not count
    client.force_login(fam)

    response = client.get(reverse("referrals:my_referrals"))

    assert response.context["unread_message_count"] == 1
