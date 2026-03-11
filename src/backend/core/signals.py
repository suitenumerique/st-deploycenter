"""Signal handlers for core models."""
# pylint: disable=unused-argument

import logging
from contextlib import contextmanager
from contextvars import ContextVar

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from core.models import Account, AccountServiceLink, ServiceSubscription
from core.webhooks import WebhookClient

logger = logging.getLogger(__name__)

# Context variable for request user (works in sync and async contexts)
_request_user: ContextVar = ContextVar("request_user", default=None)

# Context variable to temporarily suppress account webhook signals
_suppress_account_webhooks: ContextVar = ContextVar(
    "suppress_account_webhooks", default=False
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


def get_request_user():
    """Retrieve the current request user from context variable."""
    return _request_user.get()


def _mask_email(email):
    """Mask an email for logging (e.g., 'use***@test.org')."""
    if not email or "@" not in email:
        return "***"
    local, domain = email.split("@", 1)
    if len(local) > 3:
        return f"{local[:3]}***@{domain}"
    return f"{local[0]}***@{domain}"


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

    # Send webhooks
    webhook_configs = service.config.get("webhooks", [])
    if webhook_configs:
        client = WebhookClient(webhook_configs)
        # Get the user who performed the action, if available
        user = get_request_user()
        results = client.send_webhooks(
            f"subscription.{event_type}", instance, organization, service, user
        )

        # Log webhook results
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
    else:
        logger.debug("No webhook configurations found for service %s", service.name)


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

    # Send webhooks
    webhook_configs = service.config.get("webhooks", [])
    if webhook_configs:
        client = WebhookClient(webhook_configs)
        # Get the user who performed the action, if available
        user = get_request_user()
        results = client.send_webhooks(
            "subscription.deleted", instance, organization, service, user
        )

        # Log webhook results
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
    else:
        logger.debug("No webhook configurations found for service %s", service.name)


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

        webhook_configs = service.config.get("webhooks", [])
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
