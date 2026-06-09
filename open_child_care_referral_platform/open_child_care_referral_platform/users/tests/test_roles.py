from __future__ import annotations

from http import HTTPStatus

import pytest
from django.contrib.auth.models import AnonymousUser
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.test import RequestFactory
from django.views import View

from open_child_care_referral_platform.users.mixins import CoordinatorRequiredMixin
from open_child_care_referral_platform.users.mixins import FamilyRequiredMixin
from open_child_care_referral_platform.users.roles import COORDINATOR_GROUP
from open_child_care_referral_platform.users.roles import FAMILY_GROUP
from open_child_care_referral_platform.users.roles import ensure_roles
from open_child_care_referral_platform.users.tests.factories import UserFactory


class _CoordinatorOnlyView(CoordinatorRequiredMixin, View):
    def get(self, request, *args, **kwargs) -> HttpResponse:
        return HttpResponse("ok")


class _FamilyOnlyView(FamilyRequiredMixin, View):
    def get(self, request, *args, **kwargs) -> HttpResponse:
        return HttpResponse("ok")


@pytest.mark.django_db
def test_ensure_roles_is_idempotent() -> None:
    ensure_roles()
    ensure_roles()
    assert Group.objects.filter(name=COORDINATOR_GROUP).count() == 1
    assert Group.objects.filter(name=FAMILY_GROUP).count() == 1


@pytest.mark.django_db
def test_coordinator_mixin_gates_by_group() -> None:
    ensure_roles()
    coordinator = UserFactory.create()
    coordinator.groups.add(Group.objects.get(name=COORDINATOR_GROUP))
    family = UserFactory.create()
    family.groups.add(Group.objects.get(name=FAMILY_GROUP))

    view = _CoordinatorOnlyView.as_view()
    factory = RequestFactory()

    allowed = factory.get("/")
    allowed.user = coordinator
    assert view(allowed).status_code == HTTPStatus.OK

    forbidden = factory.get("/")
    forbidden.user = family
    with pytest.raises(PermissionDenied):
        view(forbidden)

    anonymous = factory.get("/")
    anonymous.user = AnonymousUser()
    assert view(anonymous).status_code == HTTPStatus.FOUND  # redirect to login


@pytest.mark.django_db
def test_family_mixin_gates_by_group() -> None:
    ensure_roles()
    family = UserFactory.create()
    family.groups.add(Group.objects.get(name=FAMILY_GROUP))
    coordinator = UserFactory.create()
    coordinator.groups.add(Group.objects.get(name=COORDINATOR_GROUP))

    view = _FamilyOnlyView.as_view()
    factory = RequestFactory()

    allowed = factory.get("/")
    allowed.user = family
    assert view(allowed).status_code == HTTPStatus.OK

    forbidden = factory.get("/")
    forbidden.user = coordinator
    with pytest.raises(PermissionDenied):
        view(forbidden)
