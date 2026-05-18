from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0019_external_management_api_key"),
    ]

    operations = [
        migrations.AddField(
            model_name="service",
            name="hidden",
            field=models.BooleanField(
                default=False,
                help_text="Whether this service should be hidden from frontend listings",
                verbose_name="hidden",
            ),
        ),
    ]
