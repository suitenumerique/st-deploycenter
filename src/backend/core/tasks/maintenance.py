"""
Housekeeping of the task machinery itself.
"""

from django_dramatiq.models import Task

from ..task_utils import cron_task, register_task

# The admin task history (django_dramatiq.Task, one row per task run) is only
# useful to check that the recent schedules ran: keep a month of it.
TASK_HISTORY_MAX_AGE = 30 * 86400


@cron_task("30 3 * * Sun")
@register_task(time_limit=600)
def prune_task_history():
    """Delete the task history rows older than ``TASK_HISTORY_MAX_AGE``."""
    Task.tasks.delete_old_tasks(TASK_HISTORY_MAX_AGE)
