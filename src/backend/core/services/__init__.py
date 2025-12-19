"""Services handlers utilities."""

import logging

from core.models import Service
from core.services.drive_service_handler import DriveServiceHandler
from core.services.messages_service_handler import MessagesServiceHandler
from core.services.service_handler import ServiceHandler

logger = logging.getLogger(__name__)


def get_service_handler(service: Service) -> ServiceHandler:
    """
    Get the service handler for the given service.
    """
    if service.type == "drive":
        return DriveServiceHandler()

    if service.type == "messages":
        return MessagesServiceHandler()

    logger.debug("No service handler found for service type: %s", service.type)
    return None
