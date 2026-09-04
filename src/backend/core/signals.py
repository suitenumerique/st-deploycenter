"""Signal handlers for core models."""
# pylint: disable=unused-argument

import logging
from contextlib import contextmanager
from contextvars import ContextVar

from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

import sentry_sdk

from core.models import Account, AccountServiceLink, ServiceSubscription
from core.services.domainnames import normalize_domains
from core.webhooks import WebhookClient

logger = logging.getLogger(__name__)

# Context variable for request user (works in sync and async contexts)
_request_user: ContextVar = ContextVar("request_user", default=None)

# Context variable to temporarily suppress account webhook signals
_suppress_account_webhooks: ContextVar = ContextVar(
    "suppress_account_webhooks", default=False
)

# Context variable to temporarily suppress the synchronous ProConnect domains push
# (e.g. bulk/programmatic subscription writes that shouldn't sync per-row).
_suppress_proconnect_sync: ContextVar = ContextVar(
    "suppress_proconnect_sync", default=False
)


@contextmanager
def request_user_context(user):
    """Context manager that sets and auto-resets the request user."""
    token = _request_user.set(user)
    try:
        yield
    finally:
        _request_user.reset(token)


@contextmanager
def suppress_account_webhooks():
    """Temporarily suppress automatic account webhook dispatch from signals."""
    token = _suppress_account_webhooks.set(True)
    try:
        yield
    finally:
        _suppress_account_webhooks.reset(token)


@contextmanager
def suppress_proconnect_sync():
    """Temporarily suppress the synchronous ProConnect domains push from signals."""
    token = _suppress_proconnect_sync.set(True)
    try:
        yield
    finally:
        _suppress_proconnect_sync.reset(token)


def get_request_user():
    """Retrieve the current request user from context variable."""
    return _request_user.get()


def _subscription_routed_domains(subscription):
    """The domains this subscription contributes to its provider's pushed set.

    Its routed domains when active, nothing when inactive — exactly what
    :func:`idp_routed_domains` unions. Used to decide whether a save actually
    changes the pushed set (and thus needs a re-push).
    """
    if not subscription.is_active:
        return frozenset()
    return frozenset(normalize_domains((subscription.metadata or {}).get("domains")))


@receiver(pre_save, sender=ServiceSubscription)
def capture_proconnect_change(sender, instance, **kwargs):
    """Record whether this save changes the subscription's routed domains.

    Lets :func:`_sync_proconnect` skip the api-partenaires push when a save touches
    neither ``is_active`` nor the domain list (e.g. an unrelated metadata edit).
    """
    # Local import to avoid an import cycle at module load.
    from core.services.proconnect import (  # noqa: PLC0415  # pylint: disable=import-outside-toplevel
        subscription_idp_id,
    )

    if instance.service.type != "proconnect":
        return
    # Stash transient flags on the instance for the post_save handler to read.
    # pylint: disable=protected-access
    if instance._state.adding or instance.pk is None:  # noqa: SLF001
        instance._proconnect_needs_sync = True  # noqa: SLF001
        instance._proconnect_previous_idp_id = None  # noqa: SLF001
        return
    old = (
        ServiceSubscription.objects.filter(pk=instance.pk)
        .select_related("service", "operator")
        .first()
    )
    # The effective idp_id is resolved per operator, so reassigning the operator
    # (admin: the field is editable) moves the subscription to another provider
    # with its domain list untouched. Comparing only the domains would read that
    # as "nothing to push" and leave BOTH providers wrong — the old one still
    # advertising the domains, the new one missing them.
    old_idp = subscription_idp_id(old) if old else None
    new_idp = subscription_idp_id(instance)
    instance._proconnect_previous_idp_id = (  # noqa: SLF001
        old_idp if old_idp and old_idp != new_idp else None
    )
    instance._proconnect_needs_sync = (  # noqa: SLF001
        old is None
        or old_idp != new_idp
        or _subscription_routed_domains(old) != _subscription_routed_domains(instance)
    )


def _sync_proconnect(instance, service):
    """Push the provider's full domain list to api-partenaires, synchronously.

    Runs inside the request's transaction so that a push failure raises and rolls
    back the subscription change (keeping local DB and the provider in sync). The
    API user then gets a sync error instead of a silent drift.

    Skips the push when the save did not change the pushed domain set (per the
    ``_proconnect_needs_sync`` flag set in :func:`capture_proconnect_change`).
    Deletes have no flag and always push (a contribution is being removed).

    FOOTGUN: this fires from ``post_save`` / ``post_delete`` signals, which Django
    does NOT emit for bulk operations — ``QuerySet.bulk_create``,
    ``QuerySet.update``, ``QuerySet.delete`` all bypass it. Any code that mutates
    proconnect ``ServiceSubscription`` rows in bulk (e.g. ``core/tasks/dpnt.py``)
    will NOT push and must reconcile the provider explicitly afterwards by calling
    ``sync_proconnect_provider(idp_id)`` (or running the ``proconnect_sync``
    command). Rollback-on-failure only holds on the request paths that open a
    transaction (the ``@transaction.atomic`` subscription viewset methods); a bare
    ``instance.save()`` in autocommit commits first, then pushes — the inverse of
    rollback. Prefer the viewset/serializer path for one-off writes.
    """
    if service.type != "proconnect" or _suppress_proconnect_sync.get():
        return
    if not getattr(instance, "_proconnect_needs_sync", True):
        return

    # Local import to avoid an import cycle at module load.
    from core.services.proconnect import (  # noqa: PLC0415  # pylint: disable=import-outside-toplevel
        sync_proconnect_provider,
        sync_proconnect_provider_for_subscription,
    )

    sync_proconnect_provider_for_subscription(instance, raise_on_error=True)

    # The subscription just moved between providers: the one it left still holds
    # its domains, and only a push recomputed from the DB will drop them.
    previous_idp_id = getattr(instance, "_proconnect_previous_idp_id", None)
    if previous_idp_id:
        sync_proconnect_provider(previous_idp_id, raise_on_error=True)


def _mask_email(email):
    """Mask an email for logging (e.g., 'use***@test.org')."""
    if not email or "@" not in email:
        return "***"
    local, domain = email.split("@", 1)
    if len(local) > 3:
        return f"{local[:3]}***@{domain}"
    return f"{local[0]}***@{domain}"


def _dispatch_subscription_webhooks(event_type, instance, organization, service):
    """Send a subscription webhook. Never raises.

    Runs after the ProConnect push, inside the caller's transaction: an exception
    escaping here would roll back a change the provider has already been told
    about — the exact drift the push-first ordering exists to prevent. Delivery is
    best-effort anyway (``WebhookClient`` already swallows per-endpoint failures);
    this extends that to the steps around them — reading the effective config and
    building the roles/base context, which touch the DB and the row's metadata.
    """
    try:
        effective_config = instance.get_effective_service_config()
        webhook_configs = effective_config.get("webhooks", [])
        if not webhook_configs:
            logger.debug("No webhook configurations found for service %s", service.name)
            return
        results = WebhookClient(webhook_configs).send_webhooks(
            event_type, instance, organization, service, get_request_user()
        )
    except Exception as exc:  # pylint: disable=broad-exception-caught
        # Swallowed, so report it: nothing downstream sees this failure otherwise.
        logger.exception(
            "Failed to dispatch %s for service %s", event_type, service.name
        )
        sentry_sdk.capture_exception(exc)
        return

    for result in results:
        if result["success"]:
            logger.info(
                "Webhook sent successfully to %s (status: %d)",
                result["url"],
                result["status_code"],
            )
        else:
            logger.error(
                "Webhook failed to %s: %s",
                result["url"],
                result["error"],
            )


@receiver(post_save, sender=ServiceSubscription)
def handle_subscription_save(sender, instance, created, **kwargs):
    """
    Handle ServiceSubscription creation and updates.

    Args:
        sender: The model class that sent the signal
        instance: The actual instance being saved
        created: Boolean indicating if this is a new instance
        **kwargs: Additional keyword arguments
    """
    event_type = "created" if created else "updated"

    # Get related objects
    organization = instance.organization
    service = instance.service

    logger.info(
        "ServiceSubscription %s: %s -> %s",
        event_type,
        organization.name,
        service.name,
    )

    # Before the webhooks: the push raises on failure, which rolls the save back,
    # and a subscription.created/updated announcing a change that never landed
    # cannot be taken back from a third party.
    _sync_proconnect(instance, service)

    _dispatch_subscription_webhooks(
        f"subscription.{event_type}", instance, organization, service
    )


@receiver(post_delete, sender=ServiceSubscription)
def handle_subscription_delete(sender, instance, **kwargs):
    """
    Handle ServiceSubscription deletion.

    Args:
        sender: The model class that sent the signal
        instance: The actual instance being deleted
        **kwargs: Additional keyword arguments
    """
    # Get related objects before deletion
    organization = instance.organization
    service = instance.service

    logger.info(
        "ServiceSubscription deleted: %s -> %s",
        organization.name,
        service.name,
    )

    # Before the webhooks, for the same reason as on save: a failed push rolls the
    # deletion back, and subscription.deleted would already be out.
    _sync_proconnect(instance, service)

    _dispatch_subscription_webhooks(
        "subscription.deleted", instance, organization, service
    )


def send_account_webhooks(account, service_ids_override=None):
    """
    Send account.updated webhooks to all active services for the account's org.

    Triggers for a given service if:
    - The account has a global role (non-empty Account.roles), OR
    - The account has (or had) a service link for that service
    """
    organization = account.organization
    user = get_request_user()
    has_global_role = bool(account.roles)

    linked_service_ids = set(
        AccountServiceLink.objects.filter(account=account)
        .values_list("service_id", flat=True)
        .distinct()
    )
    if service_ids_override:
        linked_service_ids = linked_service_ids | service_ids_override

    subscriptions = ServiceSubscription.objects.filter(
        organization=organization, is_active=True
    ).select_related("service", "operator")

    for subscription in subscriptions:
        service = subscription.service
        if not has_global_role and service.id not in linked_service_ids:
            continue

        effective_config = subscription.get_effective_service_config()
        webhook_configs = effective_config.get("webhooks", [])
        if not webhook_configs:
            continue

        client = WebhookClient(webhook_configs)
        results = client.send_account_webhooks(
            "account.updated", account, subscription, organization, service, user
        )

        for result in results:
            if result["success"]:
                logger.info(
                    "Account webhook sent successfully to %s (status: %d)",
                    result["url"],
                    result["status_code"],
                )
            else:
                logger.error(
                    "Account webhook failed to %s: %s",
                    result["url"],
                    result["error"],
                )


@receiver(post_save, sender=Account)
def handle_account_save(sender, instance, created, **kwargs):
    """Send account.updated webhooks when an account is created or modified."""
    logger.info(
        "Account %s: %s (%s)",
        "created" if created else "updated",
        _mask_email(instance.email),
        instance.organization.name,
    )
    if not _suppress_account_webhooks.get():
        send_account_webhooks(instance)


@receiver(post_delete, sender=Account)
def handle_account_delete(sender, instance, **kwargs):
    """Send account.updated webhooks when an account is deleted."""
    logger.info(
        "Account deleted: %s (%s)",
        _mask_email(instance.email),
        instance.organization.name,
    )
    if not _suppress_account_webhooks.get():
        send_account_webhooks(instance)


@receiver(post_save, sender=AccountServiceLink)
def handle_service_link_save(sender, instance, **kwargs):
    """Send account.updated webhooks when a service link is created or modified."""
    logger.info(
        "AccountServiceLink saved: %s -> %s (%s)",
        _mask_email(instance.account.email),
        instance.service.name,
        instance.role,
    )
    if not _suppress_account_webhooks.get():
        send_account_webhooks(instance.account)


@receiver(post_delete, sender=AccountServiceLink)
def handle_service_link_delete(sender, instance, **kwargs):
    """Send account.updated webhooks when a service link is deleted."""
    logger.info(
        "AccountServiceLink deleted: %s -> %s (%s)",
        _mask_email(instance.account.email),
        instance.service.name,
        instance.role,
    )
    if not _suppress_account_webhooks.get():
        send_account_webhooks(
            instance.account, service_ids_override={instance.service_id}
        )
