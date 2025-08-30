"""
Metrics scraping and processing tasks.

This module handles scraping metrics from external services and storing them in the database.
"""

import json
import logging
import time
from typing import Any, Dict, List

from django.utils import timezone

import requests
from celery import shared_task

from ..models import Metric, Organization, Service

logger = logging.getLogger(__name__)


@shared_task
def scrape_all_service_metrics():
    """
    Scrape metrics for all active services with subscriptions (Celery task).

    This task iterates through all active services and scrapes metrics
    for organizations that have active subscriptions.

    Returns:
        Dict with scrape results summary
    """
    logger.info("Starting metrics scraping for all active services")

    # Get all active services
    active_services = Service.objects.filter(is_active=True)
    logger.info("Found %d active services", active_services.count())

    total_metrics_scraped = 0
    total_metrics_stored = 0
    service_results = []

    for service in active_services:
        try:
            logger.info("Scraping metrics for service: %s", service.name)

            # Scrape metrics for this service
            service_result = scrape_service_metrics(str(service.id))

            # Update totals
            if service_result.get("status") == "success":
                total_metrics_scraped += service_result.get("metrics_scraped", 0)
                total_metrics_stored += service_result.get("metrics_stored", 0)

            service_results.append(service_result)

        except (requests.RequestException, ValueError, KeyError) as e:
            logger.error("Error processing service %s: %s", service.name, str(e))
            service_results.append(
                {
                    "service": service.name,
                    "metrics_scraped": 0,
                    "metrics_stored": 0,
                    "status": "error",
                    "error": str(e),
                }
            )

    result = {
        "total_services_processed": len(service_results),
        "total_metrics_scraped": total_metrics_scraped,
        "total_metrics_stored": total_metrics_stored,
        "service_results": service_results,
        "timestamp": timezone.now().isoformat(),
    }

    logger.info(
        "Metrics scraping completed. Total: %d scraped, %d stored",
        total_metrics_scraped,
        total_metrics_stored,
    )
    return result


@shared_task
def scrape_service_metrics(service_id: str):
    """
    Scrape metrics for a specific service (Celery task).

    Args:
        service_id: UUID of the Service

    Returns:
        Dict with scrape results
    """
    try:
        service = Service.objects.get(id=service_id)
        logger.info("Scraping metrics for service: %s", service)

        metrics_data = fetch_metrics_from_service(service)

        if metrics_data:
            metrics_stored = store_service_metrics(service, metrics_data)
            return {
                "service": str(service),
                "metrics_scraped": len(metrics_data),
                "metrics_stored": metrics_stored,
                "status": "success",
            }

        return {
            "service": str(service),
            "metrics_scraped": 0,
            "metrics_stored": 0,
            "status": "no_data",
        }

    except Service.DoesNotExist:
        logger.error("Service with ID %s not found", service_id)
        return {"status": "error", "message": "Service not found"}
    except (requests.RequestException, ValueError, KeyError) as e:
        logger.error("Error scraping metrics for service %s: %s", service_id, str(e))
        return {"status": "error", "message": str(e)}


def fetch_metrics_from_service(service: Service) -> List[Dict[str, Any]]:
    """
    Fetch metrics from a service's metrics endpoint with pagination support.

    Args:
        service: Service to fetch metrics from

    Returns:
        List of metrics data dictionaries
    """
    logger.info("Fetching metrics from service: %s", service.name)

    # Get metrics endpoint from service config
    metrics_endpoint = service.config.get("metrics_endpoint")
    if not metrics_endpoint:
        logger.warning("No metrics endpoint configured for service %s", service.name)
        return []

    # Get authentication token from service config
    auth_token = service.config.get("metrics_auth_token")
    headers = {}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"

    all_metrics = []
    offset = 0
    limit = 100  # Default page size

    while True:
        try:
            # Construct paginated URL
            paginated_url = f"{metrics_endpoint}?limit={limit}&offset={offset}"
            logger.info("Fetching metrics from: %s", paginated_url)

            # Make request to metrics endpoint
            response = requests.get(paginated_url, headers=headers, timeout=30)
            response.raise_for_status()

            # Parse response
            data = response.json()

            # Extract pagination info
            count = data.get("count", 0)
            results = data.get("results", [])

            if not results:
                logger.info("No more results at offset %d", offset)
                break

            # Add results to our collection
            all_metrics.extend(results)
            logger.info(
                "Fetched %d metrics (offset: %d, total so far: %d)",
                len(results),
                offset,
                len(all_metrics),
            )

            # Check if we've reached the end
            if offset + len(results) >= count:
                logger.info("Reached end of results. Total count: %d", count)
                break

            # Move to next page
            offset += limit

            # Mandatory pause between page calls
            logger.info("Pausing 1 second before next page request...")
            time.sleep(1)

        except requests.RequestException as e:
            logger.error("Request error at offset %d: %s", offset, str(e))
            break
        except (ValueError, KeyError, json.JSONDecodeError) as e:
            logger.error("Unexpected error at offset %d: %s", offset, str(e))
            break

    logger.info("Fetch completed. Total metrics fetched: %d", len(all_metrics))
    return all_metrics


def store_service_metrics(service: Service, metrics_data: List[Dict[str, Any]]) -> int:
    """
    Store metrics data for a service.

    Args:
        service: Service to store metrics for
        metrics_data: List of metrics data dictionaries with format:
            [{"siret": "123456789", "metrics": {"tu": 1234, "yau": 123, ...}}, ...]
            or [{"insee": "75001", "metrics": {"tu": 1234, "yau": 123, ...}}, ...]

    Returns:
        Number of metrics stored
    """
    logger.info("Storing metrics for service %s", service.name)

    # Get all organizations by both SIRET and INSEE codes
    organizations_by_siret = {
        org.siret: org
        for org in Organization.objects.filter(siret__isnull=False).exclude(siret="")
    }
    organizations_by_insee = {
        org.code_insee: org
        for org in Organization.objects.filter(code_insee__isnull=False).exclude(
            code_insee=""
        )
    }

    metrics_to_create = {}
    timestamp = timezone.now()

    for item in metrics_data:
        try:
            # Extract organization identifier (SIRET or INSEE)
            siret = item.get("siret")
            insee = item.get("insee")

            if not siret and not insee:
                logger.warning(
                    "Skipping metric without organization identifier: %s", item
                )
                continue

            # Find organization
            organization = None
            if siret and siret in organizations_by_siret:
                organization = organizations_by_siret[siret]
            elif insee and insee in organizations_by_insee:
                organization = organizations_by_insee[insee]

            if not organization:
                logger.warning(
                    "Organization not found for identifier: siret=%s, insee=%s",
                    siret,
                    insee,
                )
                continue

            # Extract metrics
            metrics = item.get("metrics", {})
            if not metrics:
                logger.warning("No metrics found in item: %s", item)
                continue

            # Process each metric type
            for metric_name, value in metrics.items():
                if value is None:
                    continue

                metrics_to_create[(service.id, organization.id, metric_name)] = Metric(
                    key=metric_name,
                    value=value,
                    service=service,
                    organization=organization,
                    timestamp=timestamp,
                )

        except (ValueError, KeyError, TypeError) as e:
            logger.error("Error processing metrics for %s: %s", item, str(e))
            continue

    # Bulk operations
    metrics_stored = 0

    if metrics_to_create:
        Metric.objects.bulk_create(
            metrics_to_create.values(),
            batch_size=1000,
            update_conflicts=True,
            update_fields=["value", "timestamp"],
            unique_fields=["service", "organization", "key"],
        )
        metrics_stored += len(metrics_to_create)
        logger.info("Bulk created %d new metrics", len(metrics_to_create))

    return metrics_stored
