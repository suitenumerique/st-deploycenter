"""Background-task API: the one seam between application code and Dramatiq.

Application code declares tasks with ``@register_task`` and schedules them with
``@cron_task``; it does not import ``dramatiq`` itself, so the queue library is
swappable from this module alone. Same shape as suitenumerique/messages.

Every task here is a periodic batch job (see ``docs/deployment.md``), so the
defaults differ from Dramatiq's:

- **No retries.** Dramatiq retries a failing actor 20 times with backoff; a
  failed nightly import would then run all day. ``max_retries`` defaults to 0
  and a failure dead-letters at once, reported to Sentry.
- **Generous time limit.** Dramatiq's default is 10 minutes, too short for the
  imports and uploads; every task declares its own budget in seconds.

Calling an actor directly (``import_dpnt_dataset(max_rows=10)``) runs it
inline, in the calling process: that is what the tests and
``manage.py run_task`` do. ``.send()`` enqueues it for the worker.
"""

import logging
from functools import lru_cache

from django.conf import settings

import dramatiq
import dramatiq_crontab

logger = logging.getLogger(__name__)

__all__ = ["cron_task", "register_task"]

QUEUE = "default"


def register_task(fn=None, *, time_limit, max_retries=0, **options):
    """Register a function as a background task.

    Args:
        time_limit: seconds after which the running task is interrupted, with
            a ``TimeLimitExceeded`` raised inside it. Required: pick a budget.
        max_retries: how many times to re-run the task after a failure. ``0``
            (the default) means a failure dead-letters immediately.
        options: passed to ``dramatiq.actor`` as-is.
    """
    options.update(
        {
            "queue_name": QUEUE,
            "max_retries": max_retries,
            "time_limit": int(time_limit * 1000),
        }
    )

    def decorator(func):
        return dramatiq.actor(func, **options)

    return decorator(fn) if fn is not None else decorator


def cron_task(crontab):
    """Run a task on a cron schedule. Apply it *above* ``@register_task``::

        @cron_task("0 8 * * *")
        @register_task(time_limit=3600)
        def import_dpnt_dataset():
            ...

    ``crontab`` is a five-field cron expression evaluated in the ``TIME_ZONE``
    of the settings (UTC). The day-of-week field must be a literal
    (``Mon``...``Sun``) or ``*``.

    The schedule is only *acted on* by the scheduler process (``manage.py
    crontab``, started by ``worker.py``), which holds a Redis lock so exactly
    one runs however many workers there are. Registering it in the web process
    is inert. ``DISABLE_TASK_SCHEDULE`` skips the registration altogether.
    """

    def decorator(actor):
        if settings.DISABLE_TASK_SCHEDULE:
            return actor

        _configure_scheduler()
        return dramatiq_crontab.cron(crontab)(actor)

    return decorator


@lru_cache(maxsize=None)
def _configure_scheduler():
    """Widen APScheduler's misfire window, once, before any job is registered.

    A job whose fire time slips past ``misfire_grace_time`` is not run late, it
    is *dropped* with a log line. The default is one second, so a brief stall
    of the scheduler process (a slow Redis round-trip) silently skips a tick:
    no import until tomorrow. Minutes of grace cost nothing, ``coalesce`` keeps
    a backlog from firing the same job repeatedly once the scheduler catches
    up, and ``max_instances`` keeps a job from being dispatched over itself.
    """
    dramatiq_crontab.scheduler.configure(
        job_defaults={"misfire_grace_time": 300, "coalesce": True, "max_instances": 1}
    )
