from django.db import migrations, models


def migrate_operator_api_keys(apps, schema_editor):
    """Move external_management_api_key from Operator.config to the dedicated field."""
    Operator = apps.get_model("core", "Operator")
    for operator in Operator.objects.filter(
        config__external_management_api_key__isnull=False
    ):
        api_key = operator.config.get("external_management_api_key")
        if api_key:
            operator.external_management_api_key = api_key
            del operator.config["external_management_api_key"]
            operator.save(update_fields=["external_management_api_key", "config"])


def reverse_migrate_operator_api_keys(apps, schema_editor):
    """Move external_management_api_key back to Operator.config."""
    Operator = apps.get_model("core", "Operator")
    for operator in Operator.objects.filter(
        external_management_api_key__isnull=False
    ):
        if operator.config is None:
            operator.config = {}
        operator.config["external_management_api_key"] = (
            operator.external_management_api_key
        )
        operator.external_management_api_key = None
        operator.save(update_fields=["external_management_api_key", "config"])


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0018_operator_org_role_admin_flag"),
    ]

    operations = [
        migrations.AddField(
            model_name="operator",
            name="external_management_api_key",
            field=models.CharField(
                blank=True,
                help_text="API key for external management of this operator's resources",
                max_length=64,
                null=True,
                unique=True,
                verbose_name="external management API key",
            ),
        ),
        migrations.AddField(
            model_name="service",
            name="external_management_api_key",
            field=models.CharField(
                blank=True,
                help_text="API key for external management via this service",
                max_length=64,
                null=True,
                unique=True,
                verbose_name="external management API key",
            ),
        ),
        migrations.RunPython(
            migrate_operator_api_keys,
            reverse_migrate_operator_api_keys,
        ),
    ]
