"""
Metrics scraping and processing tasks.

This module handles scraping metrics from external services and storing them in the database.
"""

import csv
import io
import json
import logging
import time
from typing import Any, Dict, List
from urllib.parse import urlencode

from django.db import IntegrityError
from django.utils import timezone

import requests
from celery import shared_task

from ..models import Account, Metric, Organization, Service

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
            service_result = scrape_service_metrics(service.id)

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
def scrape_service_metrics(service_id: int):
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


def scrape_service_usage_metrics(service: Service, filters: Dict[str, Any] = None):
    """
    Scrape usage metrics for a specific service (Celery task).
    """
    if filters is None:
        filters = {}
    metrics_data = fetch_usage_metrics_from_service(service, filters)
    if metrics_data:
        store_service_metrics(service, metrics_data)


def fetch_usage_metrics_from_service(
    service: Service, filters: Dict[str, Any] = None
) -> List[Dict[str, Any]]:
    """
    Fetch usage metrics from a service's usage metrics endpoint.

    Args:
        service: Service to fetch usage metrics from
        filters: Filters to apply to the usage metrics
    Returns:
        List of usage metrics data dictionaries
    """
    if filters is None:
        filters = {}
    logger.info("Fetching usage metrics from service: %s", service.name)
    usage_metrics_endpoint = service.config.get("usage_metrics_endpoint")
    if not usage_metrics_endpoint:
        logger.error(
            "No usage metrics endpoint configured for service %s", service.name
        )
        return []

    return fetch_metrics_from_endpoint(service, usage_metrics_endpoint, filters)


def fetch_metrics_from_service(service: Service) -> List[Dict[str, Any]]:
    """
    Fetch metrics from a service's metrics endpoint or CSV file.

    Args:
        service: Service to fetch metrics from

    Returns:
        List of metrics data dictionaries
    """
    logger.info("Fetching metrics from service: %s", service.name)

    # Check if service uses CSV or endpoint
    metrics_csv = service.config.get("metrics_csv")
    metrics_endpoint = service.config.get("metrics_endpoint")

    if metrics_csv:
        return fetch_metrics_from_csv(service, metrics_csv)

    if metrics_endpoint:
        return fetch_metrics_from_endpoint(service, metrics_endpoint)

    logger.warning("No metrics endpoint or CSV configured for service %s", service.name)
    return []


def fetch_metrics_from_endpoint(
    service: Service, metrics_endpoint: str, filters: Dict[str, Any] = None
) -> List[Dict[str, Any]]:
    """
    Fetch metrics from a service's metrics endpoint with pagination support.

    Args:
        service: Service to fetch metrics from
        metrics_endpoint: URL of the metrics endpoint

    Returns:
        List of metrics data dictionaries
    """
    logger.info("Fetching metrics from endpoint: %s", metrics_endpoint)

    if filters is None:
        filters = {}

    query_string = urlencode(filters) if filters else ""
    if query_string:
        separator = "&" if "?" in metrics_endpoint else "?"
        metrics_endpoint = f"{metrics_endpoint}{separator}{query_string}"

    # Get authentication token from service config
    auth_token = service.config.get("metrics_auth_token")
    headers = {}
    if auth_token:
        token_type = service.config.get("metrics_auth_token_type", "Bearer")
        headers["Authorization"] = f"{token_type} {auth_token}"

    all_metrics = []
    offset = 0
    limit = service.config.get("metrics_limit", 1000)  # Default page size

    while True:
        try:
            # Construct paginated URL
            amp = "?" if "?" not in metrics_endpoint else "&"
            paginated_url = f"{metrics_endpoint}{amp}limit={limit}&offset={offset}"
            logger.info("Fetching metrics from: %s", paginated_url)

            # Make request to metrics endpoint
            response = requests.get(paginated_url, headers=headers, timeout=30)
            response.raise_for_status()

            # Parse response
            data = response.json()

            if isinstance(data, list):
                data = {"results": data, "count": len(data)}

            # Extract pagination info
            count = data.get("count", 0)
            results = data.get("results", [])

            if not results:
                logger.info("No more results at offset %d", offset)
                break

            # Add results to our collection
            all_metrics.extend(results)
            logger.info(
                "Fetched %d results (offset: %d, total so far: %d)",
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


def fetch_metrics_from_csv(service: Service, metrics_csv: str) -> List[Dict[str, Any]]:
    """
    Fetch metrics from a CSV file with mapping configuration.

    Args:
        service: Service to fetch metrics from
        metrics_csv: URL or path to the CSV file

    Returns:
        List of metrics data dictionaries
    """
    logger.info("Fetching metrics from CSV: %s", metrics_csv)

    # Get CSV mapping configuration
    csv_mapping = service.config.get("metrics_csv_mapping", {})
    if not csv_mapping:
        logger.error("No CSV mapping configured for service %s", service.name)
        return []

    # Get authentication token from service config
    auth_token = service.config.get("metrics_auth_token")
    headers = {}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"

    delimiter = service.config.get("metrics_csv_delimiter", ",")

    try:
        # Fetch CSV content
        response = requests.get(metrics_csv, headers=headers, timeout=30)
        response.raise_for_status()

        # Parse CSV content
        csv_content = response.text
        csv_reader = csv.DictReader(io.StringIO(csv_content), delimiter=delimiter)

        all_metrics = []
        for row_num, row in enumerate(
            csv_reader, start=2
        ):  # Start at 2 because header is row 1
            try:
                # Map CSV columns to expected format using the mapping configuration
                mapped_row = map_csv_row(row, csv_mapping)
                if mapped_row:
                    all_metrics.append(mapped_row)
                else:
                    logger.warning("Skipping row %d due to mapping issues", row_num)

            except (ValueError, KeyError, TypeError) as e:
                logger.error("Error processing CSV row %d: %s", row_num, str(e))
                continue

        logger.info("CSV fetch completed. Total metrics fetched: %d", len(all_metrics))
        return all_metrics

    except requests.RequestException as e:
        logger.error("Request error fetching CSV: %s", str(e))
        return []
    except (ValueError, csv.Error) as e:
        logger.error("CSV parsing error: %s", str(e))
        return []


def map_csv_row(row: Dict[str, str], csv_mapping: Dict[str, str]) -> Dict[str, Any]:
    """
    Map a CSV row to the expected metrics format using the mapping configuration.

    Args:
        row: CSV row as dictionary
        csv_mapping: Mapping configuration (csv_column_name => target_field)

    Returns:
        Mapped row in expected format or None if mapping fails
    """
    mapped_row = {}

    # Map organization identifiers and metrics
    organization_identifiers = {}
    metrics = {}

    for csv_col, target_field in csv_mapping.items():
        if csv_col not in row:
            logger.warning("CSV column '%s' not found in row", csv_col)
            continue

        value = row[csv_col].strip() if row[csv_col] else None
        if not value:
            continue

        if target_field.startswith("metrics."):
            # This is a metric field
            metric_name = target_field[8:]  # Remove "metrics." prefix
            metrics[metric_name] = value
        else:
            # This is an organization identifier field
            organization_identifiers[target_field] = value

    # Validate that we have at least one organization identifier
    if not organization_identifiers:
        logger.warning("No organization identifier found in CSV row")
        return None

    # Add organization identifiers to mapped row
    mapped_row.update(organization_identifiers)

    # Add metrics if any
    if metrics:
        mapped_row["metrics"] = metrics
    else:
        logger.warning("No metrics found in CSV row")
        return None

    return mapped_row


def _resolve_account(
    service: Service, organization: Organization, account_data: Dict[str, Any]
):
    """Resolve or create an Account from incoming metrics account data."""
    if not account_data:
        return None

    account_type = account_data.get("type") or ""
    account_id = account_data.get("id") or ""
    account_email = account_data.get("email") or ""

    if not account_id:
        return None

    trusted = bool(service.config and service.config.get("trusted_account_binding"))
    account = Account.find_by_identifiers(
        organization=organization,
        account_type=account_type,
        external_id=account_id,
        email=account_email,
        reconcile_external_id=trusted,
    )
    if account:
        # Update email if found by external_id, email changed, and service is trusted
        if (
            trusted
            and account.external_id == account_id
            and account_email
            and account.email != account_email
        ):
            account.email = account_email
            account.save(update_fields=["email", "updated_at"])
    else:
        try:
            account = Account.objects.create(
                external_id=account_id,
                type=account_type,
                organization=organization,
                email=account_email,
            )
        except IntegrityError:
            logger.debug(
                "Account creation race condition, re-fetching: external_id=%s",
                account_id,
            )
            account = Account.find_by_identifiers(
                organization=organization,
                account_type=account_type,
                external_id=account_id,
                email=account_email,
            )

    return account


def store_service_metrics(service: Service, metrics_data: List[Dict[str, Any]]) -> int:
    """
    Store metrics data for a service.

    Args:
        service: Service to store metrics for
        metrics_data: List of metrics data dictionaries with format:
            [{"siret": "123456789", "metrics": {"tu": 1234, "yau": 123, ...}}, ...]
            or [{"insee": "75001", "metrics": {"tu": 1234, "yau": 123, ...}}, ...]
            or any other organization identifier fields

    Returns:
        Number of metrics stored
    """
    logger.info("Storing metrics for service %s", service.name)

    # Get all organizations by both SIRET and INSEE codes
    organizations_by_siret = {
        org.siret: org
        for org in Organization.objects.filter(siret__isnull=False).exclude(siret="")
    }
    organizations_by_siren = {
        org.siren: org
        for org in Organization.objects.filter(siren__isnull=False).exclude(siren="")
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
            # Extract organization identifier (any field that's not "metrics")
            organization_identifiers = {k: v for k, v in item.items() if k != "metrics"}

            if not organization_identifiers:
                logger.warning(
                    "Skipping metric without organization identifier: %s", item
                )
                continue

            # Find organization by SIRET or INSEE
            organization = None
            siret = (organization_identifiers.get("siret") or "").replace(" ", "")
            siren = (organization_identifiers.get("siren") or "").replace(" ", "")
            insee = (organization_identifiers.get("insee") or "").replace(" ", "")

            if siret and siret in organizations_by_siret:
                organization = organizations_by_siret[siret]
            elif siren and siren in organizations_by_siren:
                organization = organizations_by_siren[siren]
            elif insee and insee in organizations_by_insee:
                organization = organizations_by_insee[insee]

            if not organization:
                logger.warning(
                    "Organization not found for identifiers: %s",
                    organization_identifiers,
                )
                continue

            # logger.info("Organization found: %s", organization)

            # Get or create Account if account data is provided
            account = _resolve_account(service, organization, item.get("account", {}))

            # Extract metrics
            metrics = item.get("metrics", {})
            if not metrics:
                logger.warning("No metrics found in item: %s", item)
                continue

            # Process each metric type
            for metric_name, value in metrics.items():
                if value is None:
                    continue

                account_id_for_key = account.id if account else None
                metrics_to_create[
                    (service.id, organization.id, account_id_for_key, metric_name)
                ] = Metric(
                    key=metric_name,
                    value=value,
                    service=service,
                    organization=organization,
                    account=account,
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
            unique_fields=[
                "service",
                "organization",
                "account",
                "key",
            ],
        )
        metrics_stored += len(metrics_to_create)
        logger.info("Bulk created %d new metrics", len(metrics_to_create))

    return metrics_stored
