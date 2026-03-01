"""Split AccountServiceLink from roles JSONField (list) to one row per role."""

from django.db import migrations, models


def split_roles_to_single_role(apps, schema_editor):
    """Migrate multi-role rows into one row per role."""
    AccountServiceLink = apps.get_model("core", "AccountServiceLink")
    to_create = []
    to_delete = []

    for link in AccountServiceLink.objects.all():
        roles = link.roles or []
        if not roles:
            to_delete.append(link.pk)
            continue
        # Keep the first role on the existing row
        link.role = roles[0]
        link.save(update_fields=["role"])
        # Create extra rows for remaining roles
        for extra_role in roles[1:]:
            to_create.append(
                AccountServiceLink(
                    account_id=link.account_id,
                    service_id=link.service_id,
                    role=extra_role,
                    scope={},
                )
            )

    if to_delete:
        AccountServiceLink.objects.filter(pk__in=to_delete).delete()
    if to_create:
        AccountServiceLink.objects.bulk_create(to_create)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0014_account_unique_account_external_id_per_org_type_and_more"),
    ]

    operations = [
        # 1. Add new `role` CharField (default="" temporarily)
        migrations.AddField(
            model_name="accountservicelink",
            name="role",
            field=models.CharField(default="", max_length=100, verbose_name="role"),
            preserve_default=False,
        ),
        # 2. Add `scope` JSONField
        migrations.AddField(
            model_name="accountservicelink",
            name="scope",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text=(
                    "Scope restrictions for this role. Empty means unrestricted."
                    ' Example: {"domains": ["x.fr"]}'
                ),
                verbose_name="scope",
            ),
        ),
        # 3. Data migration: split multi-role rows
        migrations.RunPython(
            split_roles_to_single_role,
            migrations.RunPython.noop,
        ),
        # 4. Remove old `roles` JSONField
        migrations.RemoveField(
            model_name="accountservicelink",
            name="roles",
        ),
        # 5. Update unique constraint
        migrations.AlterUniqueTogether(
            name="accountservicelink",
            unique_together={("account", "service", "role")},
        ),
    ]
