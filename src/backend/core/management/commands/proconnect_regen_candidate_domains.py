"""
Generate "future allowed" ProConnect candidate domains from collectivité names
and store them in the ``candidates`` bucket of ``Organization.proconnect_domains``.

These pre-authorized domains are later exposed (per provider) by the public
allowlist API route. Run for all organizations, or narrow to a single operator.

Usage::

    python manage.py proconnect_regen_candidate_domains
    python manage.py proconnect_regen_candidate_domains --operator <operator_id>
    python manage.py proconnect_regen_candidate_domains --dry-run
"""

import logging
import uuid

from django.core.management.base import BaseCommand, CommandError

from core.models import Organization
from core.services.domains_candidates import (
    candidate_domains_for_organization,
    claimed_domains,
)
from core.services.proconnect import (
    domain_bucket,
    is_rpnt_complete,
    update_proconnect_domains,
)

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    """Populate the ``candidates`` bucket of proconnect_domains from collectivité names."""

    help = (
        "Generate candidate future ProConnect domains ('{slug}.fr') from "
        "collectivité names and store them in the proconnect_domains candidates bucket."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--operator",
            dest="operator",
            default=None,
            help="Only process organizations managed by this operator id (default: all).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would change without writing to the database.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        organizations = Organization.objects.all()
        if options["operator"]:
            try:
                operator_id = uuid.UUID(str(options["operator"]))
            except ValueError as exc:
                raise CommandError(
                    f"--operator must be a UUID (got {options['operator']!r})."
                ) from exc
            organizations = organizations.filter(operators__id=operator_id)

        # Built once for the whole batch: it is a scan of every organization, and
        # every org needs the same map to avoid proposing a homonym's domain.
        # Scoped to --operator or not, the map stays global on purpose — a domain
        # owned by a collectivité of another operator is just as taken.
        claimed = claimed_domains()

        changed = 0
        total = 0
        errors = 0
        for organization in organizations.iterator():
            total += 1
            # One bad organization must not abort the whole batch (this runs on a
            # cron over every org); count it and move on.
            try:
                changed += self._process(organization, dry_run, claimed)
            except Exception as exc:  # pylint: disable=broad-except
                errors += 1
                logger.error(
                    "Failed to regenerate candidates for organization %s (%s): %s",
                    organization.pk,
                    organization.name,
                    exc,
                    exc_info=exc,
                )
                self.stderr.write(
                    self.style.ERROR(f"{organization.name} ({organization.pk}): {exc}")
                )

        prefix = "[dry-run] " if dry_run else ""
        summary = (
            f"{prefix}{changed} organization(s) would be updated "
            f"out of {total} processed"
            if dry_run
            else f"{changed} organization(s) updated out of {total} processed"
        )
        self.stdout.write(self.style.SUCCESS(f"{summary}, {errors} error(s)."))

    def _process(self, organization, dry_run, claimed) -> int:
        """Regenerate one org's candidates; return 1 if it changed, 0 otherwise."""
        # No candidate when the org is already fully RPNT-valid; and never
        # (re)generate a domain a superuser discarded.
        if is_rpnt_complete(organization):
            new_candidates = []
        else:
            discarded = set(domain_bucket(organization, "discarded"))
            new_candidates = [
                domain
                for domain in candidate_domains_for_organization(organization, claimed)
                if domain not in discarded
            ]

        # The command only owns the "candidates" bucket; other buckets are preserved.
        current_candidates = domain_bucket(organization, "candidates")
        if set(new_candidates) == set(current_candidates):
            return 0

        if dry_run:
            self.stdout.write(
                f"{organization.name} ({organization.pk}): "
                f"candidates {current_candidates} -> {new_candidates}"
            )
        else:
            update_proconnect_domains(organization, candidates=new_candidates)
        return 1
