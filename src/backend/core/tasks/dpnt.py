"""
DPNT (Données de la Présence Numérique des Territoires) import tasks.

This module handles downloading and importing the DPNT dataset from data.gouv.fr.
"""

import gzip
import json
import logging
from collections import defaultdict
from typing import Any, Dict

from django.core.exceptions import ValidationError
from django.db import transaction

import requests
from celery import shared_task

from ..models import (
    Operator,
    OperatorOrganizationRole,
    OperatorServiceConfig,
    Organization,
    ServiceSubscription,
)
from ..services import get_service_handler

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3)
def import_dpnt_dataset(self, force_update: bool = True, max_rows: int = None):  # pylint: disable=unused-argument
    """
    Import the DPNT (Données de la Présence Numérique des Territoires) dataset from data.gouv.fr.

    Args:
        force_update: If True (default), updates existing organizations. If False, only creates new ones.
        max_rows: Maximum number of rows to process, for each type (None for all rows)

    Returns:
        Dict with import statistics
    """
    logger.info("Starting DPNT dataset import (max_rows: %s)", max_rows)

    # Download the actual dataset
    download_result = download_dpnt_dataset()

    if download_result["status"] != "success":
        logger.error("Failed to download dataset: %s", download_result["message"])
        raise ValueError(f"Dataset download failed: {download_result['message']}")

    data = download_result["data"]

    row_count_by_type = defaultdict(int)

    if len(data) < 30000:
        raise ValueError("DPNT dataset has less than 30000 rows, which is not expected")

    logger.info("Processing %d organizations from DPNT dataset", len(data))

    stats = {
        "total_processed": 0,
        "created": 0,
        "updated": 0,
        "existing": 0,
        "errors": 0,
        "errors_details": [],
    }

    with transaction.atomic():
        for item in data:
            # Limit rows if max_rows is specified for this type
            if max_rows is not None:
                if row_count_by_type[item["type"]] >= max_rows:
                    continue
                row_count_by_type[item["type"]] += 1

            # Map DPNT fields to our model fields
            org_data = {
                "name": item.get("libelle"),
                "type": item["type"],
                "siret": item.get("siret"),
                "siren": item.get("siren"),
                "population": item.get("population"),
                "code_postal": item.get("code_postal"),
                "code_insee": item.get("code_insee")
                if item["type"] == "commune"
                else None,
                "epci_libelle": item.get("epci_libelle"),
                "epci_siren": item.get("epci_siren"),
                "epci_population": item.get("epci_population"),
                "departement_code_insee": item.get("departement_code_insee"),
                "region_code_insee": item.get("region_code_insee"),
                "adresse_messagerie": item.get("adresse_messagerie"),
                "site_internet": item.get("site_internet"),
                "telephone": (item.get("telephone") or "")[0:20] or None,
                "rpnt": item.get("rpnt"),
                "service_public_url": item.get("service_public_url"),
            }

            if not org_data.get("siret"):
                logger.info(
                    "Skipped organization without SIRET: %s", org_data["code_insee"]
                )
                continue

            # Remove None values
            org_data = {k: v for k, v in org_data.items() if v is not None}

            try:
                # Try to find existing organization by INSEE code or SIREN
                existing_org = None
                if org_data.get("code_insee") and org_data["type"] == "commune":
                    existing_org = Organization.objects.filter(
                        code_insee=org_data["code_insee"]
                    ).first()
                elif org_data.get("siren"):
                    existing_org = Organization.objects.filter(
                        siren=org_data["siren"]
                    ).first()

                if existing_org and force_update:
                    # Update existing organization
                    for field, value in org_data.items():
                        setattr(existing_org, field, value)
                    existing_org.save()
                    stats["updated"] += 1
                    logger.debug("Updated organization: %s", existing_org.name)
                elif not existing_org:
                    # Create new organization
                    Organization.objects.create(**org_data)
                    stats["created"] += 1
                    logger.debug("Created organization: %s", org_data["name"])
                else:
                    logger.info("Skipped existing organization: %s", org_data["name"])
                    stats["existing"] += 1

                stats["total_processed"] += 1

            except (ValueError, KeyError, TypeError, ValidationError) as e:
                error_msg = f"Error processing organization {item.get('siret', 'Unknown')}: {str(e)}"
                logger.error(
                    "Error processing organization %s: %s",
                    item.get("siret", "Unknown"),
                    str(e),
                )
                stats["errors"] += 1
                stats["errors_details"].append(error_msg)

        stats["auto_join"] = _process_auto_join()

    logger.info("DPNT import completed. Stats: %s", stats)
    return stats


def _process_auto_join() -> Dict[str, Any]:
    """Process auto_join config for active operators.

    For each active operator with an ``auto_join`` key in its config, this
    function creates ``OperatorOrganizationRole`` and ``ServiceSubscription``
    records for every organization whose type matches the config.

    Must be called inside an existing ``transaction.atomic()`` block.
    """
    stats: Dict[str, int] = {"roles_created": 0, "subscriptions_created": 0}

    operators = Operator.objects.filter(
        is_active=True, config__has_key="auto_join"
    )

    for operator in operators:
        auto_join = operator.config.get("auto_join", {})
        types = auto_join.get("types", [])
        service_ids = auto_join.get("services", [])

        if not types or not service_ids:
            continue

        # Validate which service IDs have an OperatorServiceConfig
        valid_service_configs = OperatorServiceConfig.objects.filter(
            operator=operator, service_id__in=service_ids
        ).select_related("service")
        valid_service_ids = set(
            valid_service_configs.values_list("service_id", flat=True)
        )

        for sid in service_ids:
            if sid not in valid_service_ids:
                logger.warning(
                    "Operator %s (%s): auto_join references service %d "
                    "but no OperatorServiceConfig exists — skipping.",
                    operator.name,
                    operator.pk,
                    sid,
                )

        if not valid_service_ids:
            continue

        # Get matching organizations
        org_ids = list(
            Organization.objects.filter(type__in=types).values_list("id", flat=True)
        )

        if not org_ids:
            continue

        # Bulk create OperatorOrganizationRole
        role_objects = [
            OperatorOrganizationRole(operator=operator, organization_id=org_id)
            for org_id in org_ids
        ]
        created_roles = OperatorOrganizationRole.objects.bulk_create(
            role_objects, ignore_conflicts=True
        )
        stats["roles_created"] += len(created_roles)

        # Bulk create ServiceSubscription per valid service
        valid_services = {
            osc.service_id: osc.service for osc in valid_service_configs
        }
        for service_id in valid_service_ids:
            sub_objects = [
                ServiceSubscription(
                    operator=operator,
                    organization_id=org_id,
                    service_id=service_id,
                    is_active=True,
                )
                for org_id in org_ids
            ]
            created_subs = ServiceSubscription.objects.bulk_create(
                sub_objects, ignore_conflicts=True
            )
            stats["subscriptions_created"] += len(created_subs)

            # Create default entitlements for newly created subscriptions
            service = valid_services[service_id]
            handler = get_service_handler(service)
            if handler:
                for sub in created_subs:
                    if sub.pk:  # Only for actually inserted rows
                        handler.create_default_entitlements(sub)

    return stats


def download_dpnt_dataset() -> Dict[str, Any]:
    """
    Download the actual DPNT dataset from data.gouv.fr.
    This is a helper method called by import_dpnt_dataset.

    Returns:
        Dict with download information
    """
    logger.info("Downloading DPNT dataset from data.gouv.fr")

    try:
        # Use the direct download URL for the DPNT dataset
        download_url = "https://www.data.gouv.fr/api/1/datasets/r/fd73a12f-572c-4b04-89e9-91cc8c6ebcb3"
        logger.info("Downloading from direct URL: %s", download_url)

        response = requests.get(
            download_url, timeout=120
        )  # Longer timeout for large file
        response.raise_for_status()

        # Parse the gzipped JSON content
        try:
            data = json.loads(gzip.decompress(response.content))
            logger.info("Successfully downloaded and parsed %d records", len(data))

            return {
                "status": "success",
                "message": f"Downloaded {len(data)} records from DPNT dataset",
                "data": data,
                "dataset_info": {
                    "title": "DPNT - Données de la Présence Numérique des Territoires",
                    "download_url": download_url,
                },
            }

        except (gzip.BadGzipFile, json.JSONDecodeError) as e:
            logger.error("Failed to parse downloaded content: %s", str(e))
            return {
                "status": "error",
                "message": f"Failed to parse downloaded content: {str(e)}",
                "data": [],
            }

    except requests.RequestException as e:
        logger.error("Failed to download DPNT dataset: %s", str(e))
        return {"status": "error", "message": f"Network error: {str(e)}", "data": []}
    except (ValueError, KeyError, TypeError) as e:
        logger.error("Failed to download DPNT dataset: %s", str(e))
        return {"status": "error", "message": f"Unexpected error: {str(e)}", "data": []}
