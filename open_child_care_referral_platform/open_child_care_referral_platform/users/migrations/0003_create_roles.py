from django.db import migrations

# Mirrors open_child_care_referral_platform/users/roles.py. Hardcoded here so the
# migration stays a self-contained historical snapshot (don't import live code).
COORDINATOR_GROUP = "Coordinator"
FAMILY_GROUP = "Family"


def create_roles(apps, schema_editor):
    group_model = apps.get_model("auth", "Group")
    for name in (COORDINATOR_GROUP, FAMILY_GROUP):
        group_model.objects.get_or_create(name=name)


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0002_user_phone"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.RunPython(create_roles, migrations.RunPython.noop),
    ]
