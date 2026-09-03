"""
Fetch the *deployed* ProConnect allowlist YAML (the file that actually gates
api-partenaires, updated in their repo by PR) and cache the allowed domains per
provider (idp uid). Meant to run on a cron.

The UI reads this cache to show which of an organization's domains are already
pre-validated (routable now) vs pending the next allowlist deploy. The URL and
the cache TTL are configurable via ``PROCONNECT_DOMAIN_ALLOWLIST_URL`` and
``PROCONNECT_DOMAIN_ALLOWLIST_CACHE_TTL``.
"""

from urllib.parse import urlsplit

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

import requests
import sentry_sdk
import yaml

from core.services.proconnect import (
    ALLOWED_DOMAINS_KEY,
    redact_credentials,
    store_prevalidated_domains,
)


class Command(BaseCommand):
    """Cache the deployed ProConnect allowlist (per-idp allowed domains)."""

    help = (
        "Fetch the deployed ProConnect allowlist YAML and cache its per-idp "
        "allowed domains for the pre-validation UI."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--url",
            dest="url",
            default=None,
            help="Override PROCONNECT_DOMAIN_ALLOWLIST_URL.",
        )

    def handle(self, *args, **options):
        url = options["url"] or settings.PROCONNECT_DOMAIN_ALLOWLIST_URL
        if not url:
            raise CommandError("PROCONNECT_DOMAIN_ALLOWLIST_URL is not configured.")
        # The URL can carry credentials (a private mirror passed via --url); never
        # echo them back in an error message or a Sentry breadcrumb.
        safe_url = redact_credentials(url)

        # requests turns userinfo into a Basic auth header. Over plaintext that
        # header is readable on the wire, so refuse the combination rather than
        # leak the credential. (A same-host https -> http redirect cannot leak it:
        # requests drops Authorization when the scheme changes.) URLs without
        # credentials are unaffected — the default allowlist URL is public.
        parsed = urlsplit(url)
        if (parsed.username or parsed.password) and parsed.scheme != "https":
            raise CommandError(
                f"Refusing to send credentials over {parsed.scheme or 'no'} to "
                f"{safe_url}: use https."
            )

        # This runs on a cron, where a CommandError is only a non-zero exit nobody
        # reads: report the cause to Sentry too.
        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
        except requests.exceptions.RequestException as exc:
            sentry_sdk.capture_exception(exc)
            raise CommandError(
                f"Failed to fetch {safe_url}: {redact_credentials(str(exc))}"
            ) from exc

        try:
            data = yaml.safe_load(response.text) or {}
        except yaml.YAMLError as exc:
            sentry_sdk.capture_exception(exc)
            raise CommandError(f"Invalid YAML at {safe_url}: {exc}") from exc

        # A YAML document is not necessarily a mapping: a list or a bare scalar
        # would blow up on .get() below.
        if not isinstance(data, dict):
            raise CommandError(
                f"Invalid YAML at {safe_url}: expected a mapping, got "
                f"{type(data).__name__}."
            )

        providers = data.get("oidc_providers") or []
        count = 0
        skipped = 0
        for provider in providers:
            uid = provider.get("uid") if isinstance(provider, dict) else None
            if not uid:
                continue
            domains = provider.get(ALLOWED_DOMAINS_KEY)
            # An explicit empty list is authoritative ("nothing pre-validated");
            # a missing/malformed key is not — caching [] for it would wrongly
            # flag every domain as "not yet pre-validated" in the UI. Keep the
            # previous cache entry (or "unknown") instead.
            if not isinstance(domains, list):
                skipped += 1
                self.stderr.write(
                    self.style.WARNING(
                        f"{uid}: no {ALLOWED_DOMAINS_KEY} list in the allowlist; "
                        "keeping the previous cache entry"
                    )
                )
                continue
            cached = store_prevalidated_domains(uid, domains)
            count += 1
            self.stdout.write(f"{uid}: cached {len(cached)} allowed domains")

        if not count and not skipped:
            raise CommandError(f"No providers found in the allowlist at {safe_url}.")

        self.stdout.write(
            self.style.SUCCESS(
                f"Cached the allowlist for {count} provider(s) "
                f"({skipped} skipped, TTL "
                f"{settings.PROCONNECT_DOMAIN_ALLOWLIST_CACHE_TTL}s)."
            )
        )
