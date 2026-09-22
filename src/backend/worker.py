#!/usr/bin/env python
"""
Background task worker: consumes the queue and runs the periodic scheduler.

Usage:
    python worker.py                      # 1 process, 2 threads, scheduler on
    python worker.py --threads=4
    python worker.py --disable-scheduler  # Don't run the periodic scheduler

Every task of the application is periodic (see docs/deployment.md, "Background
tasks"). The scheduler that dispatches them (``manage.py crontab``, from
dramatiq-crontab) runs here as a supervised child process, so there is one
process type to deploy. It holds a Redis lock: with several workers, exactly
one scheduler is live and the others stand by to take over.
"""

# pylint: disable=wrong-import-position

import argparse
import importlib
import logging
import multiprocessing
import os
import subprocess
import sys
import threading

# Dramatiq's Canteen shared-memory handshake breaks under "forkserver", which
# became the default start method in Python 3.14 — worker processes boot but
# never consume. See https://github.com/Bogdanp/dramatiq/issues/701. Must be
# set before dramatiq forks anything.
multiprocessing.set_start_method("fork", force=True)

# Reserve one message per consumer thread instead of Dramatiq's default of two:
# a message reserved behind a running hour-long import would otherwise wait for
# it although another thread is idle.
os.environ.setdefault("dramatiq_queue_prefetch", "1")

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "deploycenter.settings")
os.environ.setdefault("DJANGO_CONFIGURATION", "Development")

from configurations.importer import install

install(check_options=True)

import django

django.setup()

from django.apps import apps
from django.conf import settings
from django.utils.module_loading import module_has_submodule

from dramatiq.cli import main as dramatiq_main
from dramatiq.cli import make_argument_parser

logger = logging.getLogger(__name__)

# Give a shutting-down worker long enough to finish the message in flight
# rather than killing it mid-upload.
WORKER_SHUTDOWN_TIMEOUT_MS = 600_000


def discover_tasks_modules():
    """Modules the worker must import for its actors to be registered.

    Mirrors what ``manage.py rundramatiq`` does: the first entry sets the
    global broker up (via ``django.setup()``), the rest declare the actors.
    """
    modules = ["django_dramatiq.setup"]
    for conf in apps.get_app_configs():
        for task_module in settings.DRAMATIQ_AUTODISCOVER_MODULES:
            if module_has_submodule(conf.module, task_module):
                module = f"{conf.name}.{task_module}"
                importlib.import_module(module)
                logger.info("Discovered tasks module: %r", module)
                modules.append(module)
    return modules


def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Start the background task worker.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--processes",
        "-p",
        type=int,
        default=int(os.environ.get("WORKER_PROCESSES", "1")),
        help="Number of worker processes. Default: $WORKER_PROCESSES or 1.",
    )
    parser.add_argument(
        "--threads",
        "-t",
        type=int,
        default=int(os.environ.get("WORKER_THREADS", "2")),
        help="Threads per process. Default: $WORKER_THREADS or 2.",
    )
    parser.add_argument(
        "--disable-scheduler",
        action="store_true",
        help="Don't run the periodic scheduler (enabled by default).",
    )
    parser.add_argument(
        "--loglevel",
        "-l",
        type=str,
        default="INFO",
        help="Logging level. Default: INFO",
    )
    return parser.parse_args()


class SchedulerSupervisor:
    """Run the periodic scheduler alongside this worker, as a child process.

    Supervised rather than fired-and-forgotten so the schedule survives its own
    process dying — including the ordinary case of a standby giving up on the
    lock after its blocking timeout, which must not leave this worker
    permanently unable to take over.
    """

    #: Delay before respawning an exited scheduler. Short, because the common
    #: exit is a standby timing out on the lock and needing to queue up again.
    RESTART_DELAY = 10  # seconds

    def __init__(self):
        self._stopping = threading.Event()
        # Serializes the spawn against stop(), so a shutdown that lands
        # between two respawns can't leave an orphaned scheduler behind.
        self._lock = threading.Lock()
        self._process = None
        self._thread = None

    def start(self):
        """Spawn the scheduler, then watch it in a background thread.

        The first spawn happens here, on the caller's thread, deliberately:
        Dramatiq forks its worker processes moments later, and forking a
        process whose *other* threads hold locks is how children deadlock.
        """
        self._spawn()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _spawn(self):
        """Start one scheduler process. Returns False if it could not start."""
        try:
            with self._lock:
                if self._stopping.is_set():
                    return False
                # --no-heartbeat drops the library's own log-only minute task.
                # Fixed argv, no shell, no caller-supplied input.
                self._process = subprocess.Popen(  # noqa: S603  # pylint: disable=consider-using-with
                    [sys.executable, "manage.py", "crontab", "--no-heartbeat"],
                    cwd=os.path.dirname(os.path.abspath(__file__)),
                )
        except OSError:
            logger.exception("Could not start the task scheduler")
            return False
        return True

    def _run(self):
        while not self._stopping.is_set():
            process = self._process
            if process is None:
                if not self._spawn():
                    self._stopping.wait(self.RESTART_DELAY)
                    continue
                process = self._process

            process.wait()
            if self._stopping.is_set():
                return
            logger.info("Task scheduler exited; restarting it shortly")
            self._process = None
            self._stopping.wait(self.RESTART_DELAY)

    def stop(self):
        """Shut the scheduler down and stop respawning it."""
        with self._lock:
            self._stopping.set()
            process = self._process
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()


def main():
    """Start the background task worker."""
    args = parse_args()
    tasks_modules = discover_tasks_modules()

    dramatiq_args = [
        "--processes",
        str(args.processes),
        "--threads",
        str(args.threads),
        "--worker-shutdown-timeout",
        str(WORKER_SHUTDOWN_TIMEOUT_MS),
    ]
    if args.loglevel.upper() == "DEBUG":
        dramatiq_args.append("--verbose")
    dramatiq_args += tasks_modules

    scheduler = None
    if not args.disable_scheduler:
        scheduler = SchedulerSupervisor()
        scheduler.start()

    logger.info("Starting worker")

    # Called in-process rather than through "manage.py rundramatiq", which
    # execvp's a fresh interpreter and would throw away the fork start method
    # set at the top of this file.
    try:
        return dramatiq_main(make_argument_parser().parse_args(dramatiq_args))
    finally:
        if scheduler is not None:
            scheduler.stop()


if __name__ == "__main__":
    sys.exit(main())
