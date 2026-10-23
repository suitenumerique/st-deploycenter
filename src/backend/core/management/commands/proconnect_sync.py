"""
Attach domains on the ProConnect api-partenaires API, one call each, until every
ProConnect provider (idp_id) serves what the DB routes to it.

Useful for the initial backfill and for periodic reconciliation. The provider
allows few calls per minute, so a large difference takes a while.

A domain the provider serves that no active subscription routes (attached by hand,
or by another system) is reported and left in place. ``--prune`` detaches those too.
Check what it would remove with ``proconnect_detect_drift`` first.
"""

from django.core.management.base import BaseCommand, CommandError

from core.services.proconnect import (
    BATCH_MAX_RETRY_AFTER,
    ProConnectPartnersClient,
    configured_idp_ids,
    routed_domains_by_idp,
    sync_proconnect_provider,
)


class Command(BaseCommand):
    """Reconcile ProConnect provider domains with active subscriptions."""

    help = (
        "Attach the domains the DB routes to each ProConnect provider that lacks "
        "them (or a single one with --idp-id). Domains no subscription routes are "
        "left alone unless --prune is given."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--idp-id",
            dest="idp_id",
            default=None,
            help="Only sync this idp_id (OIDC provider uid).",
        )
        parser.add_argument(
            "--prune",
            action="store_true",
            help=(
                "Also detach the domains a provider serves that no active "
                "subscription routes."
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print the domains that would be pushed without calling the API.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        client = ProConnectPartnersClient(max_retry_after=BATCH_MAX_RETRY_AFTER)
        if not client.is_configured and not dry_run:
            raise CommandError(
                "api-partenaires is not configured. Set "
                "PROCONNECT_API_PARTENAIRES_URL and "
                "PROCONNECT_API_PARTENAIRES_SECRET."
            )

        # One pass over the subscriptions for every provider, not one per provider.
        routed = routed_domains_by_idp()
        # A provider without any active subscription is read too: with --prune it
        # is emptied, without it its strays are reported.
        idp_ids = (
            {options["idp_id"]}
            if options["idp_id"]
            else set(routed) | configured_idp_ids()
        )
        if not idp_ids:
            self.stdout.write("No active ProConnect providers found.")
            return

        failures = []
        for idp_id in sorted(idp_ids):
            if dry_run:
                # Only the dry run reads it from here: sync_proconnect_provider()
                # recomputes the set under the provider's lock, so that what it
                # pushes matches the DB at push time.
                self.stdout.write(f"[dry-run] {idp_id}: {routed.get(idp_id, [])}")
                continue

            result = sync_proconnect_provider(
                idp_id, client=client, prune=options["prune"]
            )
            if result.get("success"):
                self.stdout.write(
                    self.style.SUCCESS(f"{idp_id}: OK -> {result.get('domains')}")
                )
                if result.get("unexpected"):
                    self.stdout.write(
                        self.style.WARNING(
                            f"{idp_id}: left in place, no subscription routes "
                            f"{result['unexpected']} (--prune detaches them)"
                        )
                    )
            else:
                failures.append(idp_id)
                self.stderr.write(
                    self.style.ERROR(
                        f"{idp_id}: FAILED ({result.get('error')}) -> "
                        f"{result.get('domains')}"
                    )
                )

        if failures:
            raise CommandError(
                f"Failed to push domains for {len(failures)} provider(s): "
                f"{', '.join(sorted(failures))}"
            )
