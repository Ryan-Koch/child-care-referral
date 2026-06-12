from __future__ import annotations

from django.contrib.auth.models import Group
from factory import Faker
from factory import post_generation
from factory.django import DjangoModelFactory

from open_child_care_referral_platform.users.models import User
from open_child_care_referral_platform.users.roles import COORDINATOR_GROUP
from open_child_care_referral_platform.users.roles import FAMILY_GROUP
from open_child_care_referral_platform.users.roles import ensure_roles


class UserFactory(DjangoModelFactory[User]):
    email = Faker("email")
    name = Faker("name")

    @post_generation
    def password(self: User, create: bool, extracted: str | None, **kwargs):  # noqa: FBT001
        password = (
            extracted
            if extracted
            else Faker(
                "password",
                length=42,
                special_chars=True,
                digits=True,
                upper_case=True,
                lower_case=True,
            ).evaluate(None, None, extra={"locale": None})
        )
        self.set_password(password)
        if create:
            self.save()

    class Meta:
        model = User
        django_get_or_create = ["email"]
        skip_postgeneration_save = True


def make_user_in_group(group_name: str) -> User:
    """A saved user who is a member of ``group_name`` (roles ensured)."""
    ensure_roles()
    user = UserFactory.create()
    user.groups.add(Group.objects.get(name=group_name))
    return user


def make_family() -> User:
    return make_user_in_group(FAMILY_GROUP)


def make_coordinator() -> User:
    return make_user_in_group(COORDINATOR_GROUP)
