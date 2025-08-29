"""Deploy Center celery configuration file."""

import os

from celery import Celery
from configurations.importer import install

# Set the default Django settings module for the 'celery' program.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "deploycenter.settings")
os.environ.setdefault("DJANGO_CONFIGURATION", "Development")

install(check_options=True)

app = Celery("deploycenter")

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
# - namespace='CELERY' means all celery-related configuration keys
#   should have a `CELERY_` prefix.
app.config_from_object("django.conf:settings", namespace="CELERY")

# Load task modules from all registered Django apps.
app.autodiscover_tasks()

# Configure beat schedule
# This can be disabled manually, for example when pushing the application for the first time
# to a PaaS service when no migration was applied yet.
if not os.environ.get("DISABLE_CELERY_BEAT_SCHEDULE"):
    app.conf.beat_schedule = {}
