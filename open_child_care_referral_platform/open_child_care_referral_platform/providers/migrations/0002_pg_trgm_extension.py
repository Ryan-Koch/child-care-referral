from django.contrib.postgres.operations import TrigramExtension
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("providers", "0001_initial"),
    ]

    operations = [
        TrigramExtension(),
    ]
