"""
Push the full list of authorized domains to the ProConnect api-partenaires API
for every active ProConnect provider (idp_id).

Useful for the initial backfill and for periodic reconciliation.
"""

from django.core.management.base import BaseCommand, CommandError

from core.services.proconnect import (
    ProConnectPartnersClient,
    routed_domains_by_idp,
    sync_proconnect_provider,
)


class Command(BaseCommand):
    """Reconcile ProConnect provider domains with active subscriptions."""

    help = (
        "Push authorized domains to the ProConnect api-partenaires API for all "
        "active providers (or a single one with --idp-id)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--idp-id",
            dest="idp_id",
            default=None,
            help="Only sync this idp_id (OIDC provider uid).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print the domains that would be pushed without calling the API.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        client = ProConnectPartnersClient()
        if not client.is_configured and not dry_run:
            raise CommandError(
                "api-partenaires is not configured. Set "
                "PROCONNECT_API_PARTENAIRES_URL and "
                "PROCONNECT_API_PARTENAIRES_SECRET."
            )

        # One pass over the subscriptions for every provider, not one per provider.
        routed = routed_domains_by_idp()
        idp_ids = {options["idp_id"]} if options["idp_id"] else set(routed)
        if not idp_ids:
            self.stdout.write("No active ProConnect providers found.")
            return

        failures = []
        for idp_id in sorted(idp_ids):
            if dry_run:
                # Only the dry run reads it from here: sync_proconnect_provider()
                # recomputes the set under the provider's lock, so that what it
                # PATCHes matches the DB at push time.
                self.stdout.write(f"[dry-run] {idp_id}: {routed.get(idp_id, [])}")
                continue

            result = sync_proconnect_provider(idp_id, client=client)
            if result.get("success"):
                self.stdout.write(
                    self.style.SUCCESS(f"{idp_id}: OK -> {result.get('domains')}")
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
