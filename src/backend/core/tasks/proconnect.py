"""
ProConnect periodic tasks.
"""

from django.core.management import call_command

from ..task_utils import cron_task, register_task


@cron_task("0 * * * *")
@register_task(time_limit=600)
def fetch_proconnect_prevalidated():
    """Cache the deployed ProConnect allowlist (see docs/proconnect_domains.md).

    The logic lives in the ``proconnect_fetch_prevalidated`` management
    command, which stays runnable by hand; this task is its hourly schedule. A
    ``CommandError`` propagates and fails the task, so it reaches Sentry.
    """
    call_command("proconnect_fetch_prevalidated")
