"""The periodic schedule: what runs when, and how tasks are declared."""

from unittest import mock

from django.test import override_settings

import dramatiq
import dramatiq_crontab
import pytest
from django_dramatiq.models import Task

from core import tasks
from core.task_utils import cron_task, register_task

# The schedule the worker runs (UTC). docs/deployment.md lists the same table:
# keep both in sync.
SCHEDULE = {
    "fetch_proconnect_prevalidated": "0 * * * *",
    "scrape_all_service_metrics": "0 2 * * *",
    "import_dpnt_dataset": "0 8 * * *",
    "upload_deployment_datasets": "0 */4 * * *",
    "prune_task_history": "30 3 * * Sun",
}


def _scheduled_jobs():
    """The jobs registered with the scheduler, by actor name."""
    return {job.name: job for job in dramatiq_crontab.scheduler.get_jobs()}


def test_every_task_of_the_schedule_is_registered():
    """Each task of the schedule is a registered actor with a cron job."""
    jobs = _scheduled_jobs()
    for name, crontab in SCHEDULE.items():
        actor = getattr(tasks, name)
        assert isinstance(actor, dramatiq.Actor), name
        assert name in jobs, f"{name} is not scheduled"
        minute, hour, day, month, weekday = crontab.split()
        fields = {field.name: str(field) for field in jobs[name].trigger.fields}
        assert fields["minute"] == minute, name
        assert fields["hour"] == hour, name
        assert fields["day"] == day, name
        assert fields["month"] == month, name
        assert fields["day_of_week"] == weekday.lower(), name


def test_only_the_tasks_of_the_schedule_are_scheduled():
    """A task scheduled without being listed above is undocumented."""
    scheduled = {name for name in _scheduled_jobs() if hasattr(tasks, name)}
    assert scheduled == set(SCHEDULE)


def test_register_task_defaults():
    """No retries, one queue, and a time limit in milliseconds."""

    @register_task(time_limit=42)
    def some_task():
        return "ran"

    assert some_task.queue_name == "default"
    assert some_task.options["max_retries"] == 0
    assert some_task.options["time_limit"] == 42_000
    # Calling the actor runs it inline.
    assert some_task() == "ran"


def test_cron_task_registration_is_skipped_when_the_schedule_is_disabled():
    """DISABLE_TASK_SCHEDULE leaves the actor alone and registers no job."""
    before = set(_scheduled_jobs())
    with override_settings(DISABLE_TASK_SCHEDULE=True):

        @cron_task("0 0 * * *")
        @register_task(time_limit=1)
        def unscheduled_task():
            pass

    assert isinstance(unscheduled_task, dramatiq.Actor)
    assert set(_scheduled_jobs()) == before


def test_cron_task_refuses_a_numeric_weekday():
    """dramatiq-crontab wants literal weekdays; a typo must not pass silently."""
    with pytest.raises(ValueError, match="literal day of week"):

        @cron_task("0 0 * * 1")
        @register_task(time_limit=1)
        def bad_task():
            pass


def test_fetch_proconnect_prevalidated_runs_the_command():
    """The hourly task is the management command, nothing more."""
    with mock.patch("core.tasks.proconnect.call_command") as call_command:
        tasks.fetch_proconnect_prevalidated()
    call_command.assert_called_once_with("proconnect_fetch_prevalidated")


@pytest.mark.django_db
def test_prune_task_history_deletes_old_rows():
    """Rows older than a month go, recent ones stay."""
    with mock.patch.object(Task.tasks, "delete_old_tasks") as delete_old_tasks:
        tasks.prune_task_history()
    delete_old_tasks.assert_called_once_with(30 * 86400)
