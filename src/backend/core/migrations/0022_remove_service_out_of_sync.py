from django.db import migrations


def remove_out_of_sync(apps, schema_editor):
    """Drop the ``out_of_sync`` flag the hourly drift check used to store.

    Nothing reads it anymore. Left in place, it would show up in the admin, in the
    effective operator config and in duplicated services.
    """
    Service = apps.get_model("core", "Service")
    for service in Service.objects.filter(config__has_key="out_of_sync"):
        config = dict(service.config)
        del config["out_of_sync"]
        Service.objects.filter(pk=service.pk).update(config=config)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0021_organization_proconnect_domains"),
    ]

    operations = [
        migrations.RunPython(remove_out_of_sync, migrations.RunPython.noop),
    ]
