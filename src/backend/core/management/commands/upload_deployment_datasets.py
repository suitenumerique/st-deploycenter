"""
Upload the deployment datasets to data.gouv.fr, by hand.

The worker runs the same uploads every four hours (``upload_deployment_datasets``
task, see docs/deployment.md). This command is for running them outside the
schedule, all of them or a selection, and exits non-zero if any failed.
"""

from django.core.management.base import BaseCommand, CommandError

from core.tasks.datagouv import DATASET_TASKS, run_dataset_uploads


class Command(BaseCommand):
    """Upload the deployment datasets to data.gouv.fr."""

    help = (
        "Upload every deployment dataset to data.gouv.fr "
        f"({', '.join(DATASET_TASKS)}), or only those given as arguments."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "datasets",
            nargs="*",
            choices=DATASET_TASKS,
            metavar="TASK",
            help="Upload only these datasets (default: all, in that order).",
        )

    def handle(self, *args, **options):
        def report(task_name, outcome):
            if isinstance(outcome, Exception):
                self.stderr.write(self.style.ERROR(f"{task_name} failed: {outcome}"))
            else:
                self.stdout.write(self.style.SUCCESS(f"{task_name}: {outcome}"))

        _results, failed = run_dataset_uploads(options["datasets"], report=report)
        if failed:
            raise CommandError(f"{len(failed)} upload(s) failed: {', '.join(failed)}")
