import re
import django.contrib.auth.validators
from django.db import migrations, models


def backfill_usernames(apps, schema_editor):
    """Give every existing user a unique username derived from their email."""
    User = apps.get_model("accounts", "User")
    for user in User.objects.all().order_by("date_joined"):
        base = (user.email or "user").split("@")[0]
        base = re.sub(r"[^A-Za-z0-9._-]", "", base) or "user"
        candidate = base
        suffix = 1
        while User.objects.filter(username=candidate).exclude(pk=user.pk).exists():
            suffix += 1
            candidate = f"{base}{suffix}"
        user.username = candidate
        user.save(update_fields=["username"])


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0002_alter_user_groups_alter_user_is_superuser_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="username",
            field=models.CharField(max_length=150, null=True),
        ),
        migrations.RunPython(backfill_usernames, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="user",
            name="username",
            field=models.CharField(
                help_text="Required. 150 characters or fewer. Letters, digits and @/./+/-/_ only.",
                max_length=150,
                unique=True,
                validators=[django.contrib.auth.validators.UnicodeUsernameValidator()],
            ),
        ),
    ]
