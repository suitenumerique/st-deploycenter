"""
Detect drift between our intended ProConnect routing and what is actually live on
the api-partenaires provider(s).

For each provider (idp_id) we GET the live configuration and compare its
``attached_email_domains`` to
the exact set we intend to route — the union of ``metadata["domains"]`` across
active subscriptions resolving to that idp (:func:`idp_routed_domains`). The two
lists must match EXACTLY; any difference is reported and the command exits
non-zero so a cron can alert.

Never writes to the provider. In the DB it only maintains ``Service.config["out_of_sync"]``:
set on the services of a drifted provider (which blocks their subscription writes
in the API), cleared once every provider of the service is read and in sync.
"""

from django.core.management.base import BaseCommand, CommandError

from core.services.proconnect import (
    BATCH_MAX_RETRY_AFTER,
    ProConnectPartnersClient,
    check_providers_drift,
    out_of_sync_idp_ids,
    routed_domains_by_idp,
    update_out_of_sync,
)


class Command(BaseCommand):
    """Warn when a provider's live domains diverge from our intended routing."""

    help = (
        "Compare each ProConnect provider's live domains (GET api-partenaires) with "
        "the exact set we intend to route; report any drift and exit non-zero."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--idp-id",
            dest="idp_id",
            default=None,
            help="Only check this provider uid.",
        )

    def handle(self, *args, **options):
        client = ProConnectPartnersClient(max_retry_after=BATCH_MAX_RETRY_AFTER)
        if not client.is_configured:
            raise CommandError("api-partenaires is not configured.")

        # One pass over the subscriptions for every provider, not one per provider.
        routed = routed_domains_by_idp()
        # Providers of flagged services are always rechecked, even when they no
        # longer have an active subscription: otherwise nothing could clear the flag.
        idp_ids = (
            {options["idp_id"]}
            if options["idp_id"]
            else set(routed) | out_of_sync_idp_ids()
        )
        if not idp_ids:
            self.stdout.write("No active ProConnect providers found.")
            return

        report = check_providers_drift(idp_ids, client, routed)
        update_out_of_sync(report)

        for idp_id in sorted(idp_ids):
            if idp_id in report.in_sync:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"{idp_id}: in sync ({report.in_sync[idp_id]} domains)"
                    )
                )
            elif idp_id in report.drifted:
                drift = report.drifted[idp_id]
                self.stderr.write(
                    self.style.WARNING(
                        f"{idp_id}: DRIFT: missing on provider: {drift.missing}; "
                        f"unexpected on provider: {drift.unexpected}"
                    )
                )
            else:
                self.stderr.write(
                    self.style.ERROR(
                        f"{idp_id}: GET failed: {report.unreadable[idp_id]}"
                    )
                )

        drifted, unreadable = sorted(report.drifted), sorted(report.unreadable)
        if drifted or unreadable:
            problems = []
            if unreadable:
                problems.append(
                    f"{len(unreadable)} provider(s) could not be read: "
                    f"{', '.join(sorted(unreadable))}"
                )
            if drifted:
                problems.append(
                    f"{len(drifted)} provider(s) out of sync: "
                    f"{', '.join(sorted(drifted))}"
                )
            raise CommandError("; ".join(problems))
