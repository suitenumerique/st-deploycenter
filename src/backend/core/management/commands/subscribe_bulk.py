"""
Bulk (un)subscribe organizations to a service.

The organization set is selected with arbitrary ORM lookups, so the command is
not tied to any particular backfill.

Usage::

    # every commune -> service 7, for one operator
    python manage.py subscribe_bulk subscribe --service 7 \
        --operator 9f5624fc-ef99-4d10-ae3f-403a81eb16ef --filter type=commune

    # only the ones that operator manages, above 1000 inhabitants
    python manage.py subscribe_bulk subscribe --service 7 --operator <uuid> \
        --filter type=commune --filter operators=<uuid> --filter population__gte=1000

    # remove them again (deletes the rows; --soft only flips is_active)
    python manage.py subscribe_bulk unsubscribe --service 7 --operator <uuid> \
        --filter type=commune

``--filter``/``--exclude`` take ``lookup=value`` pairs applied to the Organization
queryset. ``__in`` lookups split the value on commas; ``true``/``false``/``null``
are converted. Always check the plan with ``--dry-run`` first.

Rows are written one by one so that entitlements and webhooks still fire, but the
per-row ProConnect push is suppressed: each affected provider is pushed once at
the end instead of once per organization.
"""

import logging

from django.core.exceptions import FieldError, ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

import sentry_sdk

from core.models import Operator, Organization, Service, ServiceSubscription
from core.services.proconnect import (
    effective_config_memo,
    subscription_idp_id,
    sync_proconnect_provider,
)
from core.signals import suppress_proconnect_sync

logger = logging.getLogger(__name__)

PROGRESS_EVERY = 500
# Organizations fetched per query while iterating the selection.
FETCH_CHUNK = 500


def parse_lookup(pair):
    """Parse a ``lookup=value`` argument into a (lookup, value) tuple."""
    if "=" not in pair:
        raise CommandError(f"Expected lookup=value, got {pair!r}.")

    lookup, raw = pair.split("=", 1)
    lookup = lookup.strip()
    if not lookup:
        raise CommandError(f"Empty lookup in {pair!r}.")

    if lookup.endswith("__in"):
        return lookup, [v.strip() for v in raw.split(",") if v.strip()]

    lowered = raw.strip().lower()
    if lowered in ("true", "false"):
        return lookup, lowered == "true"
    if lowered in ("null", "none"):
        return lookup, None
    return lookup, raw


class Command(BaseCommand):
    """Create, deactivate or delete service subscriptions in bulk."""

    help = "Bulk subscribe or unsubscribe organizations to a service."

    def add_arguments(self, parser):
        parser.add_argument(
            "action",
            choices=["subscribe", "unsubscribe"],
            help="subscribe: create missing subscriptions. unsubscribe: remove them.",
        )
        parser.add_argument(
            "--service",
            type=int,
            required=True,
            help="Service id to (un)subscribe to.",
        )
        parser.add_argument(
            "--operator",
            default=None,
            help=(
                "Operator id owning the subscriptions. Required to subscribe; "
                "restricts the rows to unsubscribe when given."
            ),
        )
        parser.add_argument(
            "--filter",
            dest="filters",
            action="append",
            default=[],
            metavar="LOOKUP=VALUE",
            help="Organization filter, repeatable (e.g. --filter type=commune).",
        )
        parser.add_argument(
            "--exclude",
            dest="excludes",
            action="append",
            default=[],
            metavar="LOOKUP=VALUE",
            help="Organization exclusion, repeatable.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Only process the first N organizations (ordered by name).",
        )
        parser.add_argument(
            "--inactive",
            action="store_true",
            help="subscribe: create the subscriptions with is_active=False.",
        )
        parser.add_argument(
            "--update-existing",
            action="store_true",
            help="subscribe: also flip is_active on already existing subscriptions.",
        )
        parser.add_argument(
            "--soft",
            action="store_true",
            help="unsubscribe: set is_active=False instead of deleting the rows.",
        )
        parser.add_argument(
            "--no-proconnect-sync",
            action="store_true",
            help="Skip the final ProConnect domains push to api-partenaires.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would change without writing to the database.",
        )
        parser.add_argument(
            "--noinput",
            "--no-input",
            action="store_false",
            dest="interactive",
            help="Do not ask for confirmation before deleting rows.",
        )

    def handle(self, *args, **options):
        action = options["action"]
        dry_run = options["dry_run"]

        service = self._get_service(options["service"])
        operator = self._get_operator(options["operator"])
        if action == "subscribe" and operator is None:
            raise CommandError("--operator is required to subscribe.")

        organization_ids = self._select_organizations(options)
        self.stdout.write(
            f"{len(organization_ids)} organization(s) matched, "
            f"service {service.name} (#{service.pk}, type={service.type})."
        )
        if not organization_ids:
            return

        # Effective configs are read once per (service, operator) pair instead of
        # once per row, and idps are collected before the writes so that deleted
        # rows are still pushed.
        with effective_config_memo():
            if action == "subscribe":
                idp_ids = self._subscribe(
                    service, operator, organization_ids, options, dry_run
                )
            else:
                idp_ids = self._unsubscribe(
                    service, operator, organization_ids, options, dry_run
                )

        if idp_ids and not dry_run and not options["no_proconnect_sync"]:
            self._push_proconnect(idp_ids)

    def _get_service(self, service_id):
        """Return the target service or fail."""
        try:
            return Service.objects.get(pk=service_id)
        except Service.DoesNotExist as exc:
            raise CommandError(f"No service with id {service_id}.") from exc

    def _get_operator(self, operator_id):
        """Return the target operator, or None when not given."""
        if not operator_id:
            return None
        try:
            return Operator.objects.get(pk=operator_id)
        except (Operator.DoesNotExist, ValidationError, ValueError) as exc:
            raise CommandError(f"No operator with id {operator_id!r}.") from exc

    def _select_organizations(self, options):
        """Return the ids of the organizations matching --filter/--exclude/--limit."""
        queryset = Organization.objects.all()
        try:
            for pair in options["filters"]:
                lookup, value = parse_lookup(pair)
                queryset = queryset.filter(**{lookup: value})
            for pair in options["excludes"]:
                lookup, value = parse_lookup(pair)
                queryset = queryset.exclude(**{lookup: value})
            # Two organizations can match twice through a m2m lookup (e.g. operators).
            queryset = queryset.order_by("name").distinct()
            # `is not None`, so an explicit --limit 0 selects nothing instead of
            # silently meaning "no limit".
            if options["limit"] is not None:
                queryset = queryset[: options["limit"]]
            return list(queryset.values_list("pk", flat=True))
        except (FieldError, ValidationError, ValueError) as exc:
            raise CommandError(f"Invalid filter: {exc}") from exc

    def _subscribe(self, service, operator, organization_ids, options, dry_run):
        """Create the missing subscriptions; return the affected idp_ids."""
        is_active = not options["inactive"]
        existing = ServiceSubscription.objects.filter(
            service=service, organization_id__in=organization_ids
        )
        existing_by_org = {sub.organization_id: sub for sub in existing}
        # (organization, service) is unique, so a row owned by another operator
        # blocks this one: we cannot create a second subscription, and flipping
        # theirs would silently take over a service another operator manages.
        # Report those instead of folding them into "already subscribed".
        conflicts = [
            sub for sub in existing_by_org.values() if sub.operator_id != operator.id
        ]
        mine = [
            sub for sub in existing_by_org.values() if sub.operator_id == operator.id
        ]
        missing_ids = [oid for oid in organization_ids if oid not in existing_by_org]
        to_update = (
            [sub for sub in mine if sub.is_active != is_active]
            if options["update_existing"]
            else []
        )

        self.stdout.write(
            f"{len(missing_ids)} to create (is_active={is_active}), "
            f"{len(mine)} already subscribed "
            f"({len(to_update)} to update), operator {operator.name}."
        )
        if conflicts:
            self.stderr.write(
                self.style.WARNING(
                    f"{len(conflicts)} organization(s) already subscribed to "
                    f"{service.name} under another operator; left untouched: "
                    + ", ".join(
                        f"{sub.organization_id} ({sub.operator_id})"
                        for sub in conflicts[:10]
                    )
                    + (" …" if len(conflicts) > 10 else "")
                )
            )
        if dry_run or (not missing_ids and not to_update):
            self.stdout.write(self.style.SUCCESS("Nothing written."))
            return set()

        idp_ids = set()
        created = errors = updated = 0
        with suppress_proconnect_sync():
            for organization in self._iter_organizations(missing_ids):
                subscription = ServiceSubscription(
                    organization=organization,
                    operator=operator,
                    service=service,
                    is_active=is_active,
                )
                if self._write(subscription.save, organization):
                    created += 1
                    self._progress(created, len(missing_ids), "created")
                else:
                    errors += 1

            for subscription in to_update:
                subscription.is_active = is_active
                if self._write(subscription.save, subscription.organization):
                    updated += 1
                else:
                    errors += 1

            idp_ids = self._collect_idp_ids(service, [operator])

        self.stdout.write(
            self.style.SUCCESS(
                f"{created} created, {updated} updated, {errors} error(s)."
            )
        )
        return idp_ids

    def _unsubscribe(self, service, operator, organization_ids, options, dry_run):
        """Delete (or deactivate) the subscriptions; return the affected idp_ids."""
        soft = options["soft"]
        subscriptions = ServiceSubscription.objects.filter(
            service=service, organization_id__in=organization_ids
        ).select_related("organization", "operator")
        if operator:
            subscriptions = subscriptions.filter(operator=operator)
        if soft:
            subscriptions = subscriptions.filter(is_active=True)

        subscriptions = list(subscriptions)
        verb = "deactivate" if soft else "DELETE"
        self.stdout.write(f"{len(subscriptions)} subscription(s) to {verb}.")
        if dry_run or not subscriptions:
            self.stdout.write(self.style.SUCCESS("Nothing written."))
            return set()

        if options["interactive"] and not soft:
            try:
                answer = input(
                    f"Permanently delete {len(subscriptions)} subscription(s)? [y/N] "
                )
            except EOFError as exc:
                raise CommandError("No tty to confirm on; pass --noinput.") from exc
            if answer.strip().lower() not in ("y", "yes"):
                raise CommandError("Aborted.")

        # Collected before the writes: once the rows are gone the operators are
        # unreachable, and the push below needs their idps.
        idp_ids = self._collect_idp_ids(
            service, {sub.operator_id: sub.operator for sub in subscriptions}.values()
        )

        done = errors = 0
        with suppress_proconnect_sync():
            for subscription in subscriptions:
                if soft:
                    subscription.is_active = False
                    write = subscription.save
                else:
                    write = subscription.delete
                if self._write(write, subscription.organization):
                    done += 1
                    self._progress(done, len(subscriptions), f"{verb.lower()}d")
                else:
                    errors += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"{done} subscription(s) {verb.lower()}d, {errors} error(s)."
            )
        )
        return idp_ids

    def _iter_organizations(self, organization_ids):
        """Yield the organizations for the given ids, in chunks."""
        for start in range(0, len(organization_ids), FETCH_CHUNK):
            chunk = organization_ids[start : start + FETCH_CHUNK]
            yield from Organization.objects.filter(pk__in=chunk)

    def _write(self, func, organization):
        """Run one row write in its own transaction; return False on failure."""
        # One bad row must not abort the batch, and must not leave a half-written
        # subscription (save() also creates entitlements) behind.
        try:
            with transaction.atomic():
                func()
        except Exception as exc:  # pylint: disable=broad-except
            # Swallowed so one bad row can't abort the batch — so report it, or a
            # run that prints "3 error(s)" leaves no trace of what they were.
            sentry_sdk.capture_exception(exc)
            logger.error(
                "Subscription write failed for organization %s (%s): %s",
                organization.pk,
                organization.name,
                exc,
                exc_info=exc,
            )
            self.stderr.write(
                self.style.ERROR(f"{organization.name} ({organization.pk}): {exc}")
            )
            return False
        return True

    def _collect_idp_ids(self, service, operators):
        """Return the idp_ids of the (service, operator) pairs touched."""
        if service.type != "proconnect":
            return set()
        idp_ids = set()
        for operator in operators:
            idp_id = subscription_idp_id(
                ServiceSubscription(service=service, operator=operator)
            )
            if idp_id:
                idp_ids.add(idp_id)
        return idp_ids

    def _push_proconnect(self, idp_ids):
        """Push the full domain list once per affected ProConnect provider."""
        failures = []
        for idp_id in sorted(idp_ids):
            result = sync_proconnect_provider(idp_id)
            if result.get("success"):
                self.stdout.write(
                    self.style.SUCCESS(f"{idp_id}: pushed {result.get('domains')}")
                )
            elif result.get("skipped"):
                self.stdout.write(f"{idp_id}: api-partenaires not configured, skipped.")
            else:
                failures.append(idp_id)
                self.stderr.write(
                    self.style.ERROR(f"{idp_id}: push FAILED ({result.get('error')})")
                )
        if failures:
            raise CommandError(
                f"Rows written but the domains push failed for {', '.join(failures)}. "
                f"Re-run `manage.py proconnect_sync`."
            )

    def _progress(self, done, total, label):
        """Print a progress line every PROGRESS_EVERY rows."""
        if done % PROGRESS_EVERY == 0:
            self.stdout.write(f"{done}/{total} {label}…")
