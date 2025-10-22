"""Signal handlers for core models."""
# pylint: disable=unused-argument

import logging

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from core.models import ServiceSubscription
from core.webhooks import WebhookClient

logger = logging.getLogger(__name__)


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
        results = client.send_webhooks(
            f"subscription.{event_type}", instance, organization, service
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
        results = client.send_webhooks(
            "subscription.deleted", instance, organization, service
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
