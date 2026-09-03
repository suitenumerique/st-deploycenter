"""
Detect drift between our intended ProConnect routing and what is actually live on
the api-partenaires provider(s).

For each provider (idp_id) we GET the live configuration and compare its
``attached_email_domains`` to
the exact set we intend to route — the union of ``metadata["domains"]`` across
active subscriptions resolving to that idp (:func:`idp_routed_domains`). The two
lists must match EXACTLY; any difference is reported and the command exits
non-zero so a cron can alert.

Read-only: this command never writes to the DB or the provider.
"""

from django.core.management.base import BaseCommand, CommandError

import sentry_sdk

from core.services.domainnames import normalize_domains
from core.services.proconnect import (
    ATTACHED_EMAIL_DOMAINS_KEY,
    ProConnectPartnersClient,
    ProConnectPartnersError,
    routed_domains_by_idp,
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
        client = ProConnectPartnersClient()
        if not client.is_configured:
            raise CommandError("api-partenaires is not configured.")

        # One pass over the subscriptions for every provider, not one per provider.
        routed = routed_domains_by_idp()
        idp_ids = {options["idp_id"]} if options["idp_id"] else set(routed)
        if not idp_ids:
            self.stdout.write("No active ProConnect providers found.")
            return

        drifted = []
        unreadable = []
        for idp_id in sorted(idp_ids):
            try:
                config = client.get_configuration(idp_id)
            except ProConnectPartnersError as exc:
                unreadable.append(idp_id)
                sentry_sdk.capture_exception(exc)
                self.stderr.write(self.style.ERROR(f"{idp_id}: GET failed: {exc}"))
                continue

            # Normalize both sides the same way, or a value the provider accepts
            # but we would never store reads as permanent drift.
            live = normalize_domains(config.get(ATTACHED_EMAIL_DOMAINS_KEY) or [])
            intended = routed.get(idp_id, [])  # already sorted + normalized
            if live == intended:
                self.stdout.write(
                    self.style.SUCCESS(f"{idp_id}: in sync ({len(live)} domains)")
                )
                continue

            drifted.append(idp_id)
            missing = sorted(
                set(intended) - set(live)
            )  # we route it, provider lacks it
            unexpected = sorted(set(live) - set(intended))  # provider has it, we don't
            self.stderr.write(
                self.style.WARNING(
                    f"{idp_id}: DRIFT — missing on provider: {missing}; "
                    f"unexpected on provider: {unexpected}"
                )
            )

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
