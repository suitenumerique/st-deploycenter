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
from ..services.proconnect import org_rpnt_valid_domains, update_proconnect_domains

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

    # One transaction per organization, NOT one for the whole import:
    # update_proconnect_domains() takes select_for_update() on the row it merges,
    # and a single outer transaction would hold those locks on every organization
    # it touched until the import ends — minutes during which the superuser
    # domain-edit endpoint (which locks the same row) blocks.
    for item in data:
        # Parsing lives inside the try too: `data` is a downloaded document, so a
        # row that is not a dict (AttributeError) or is missing "type" (KeyError)
        # is bad input, not a bug — it must cost one row, not the whole import.
        try:
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
                    "Skipped organization without SIRET: %s", org_data.get("code_insee")
                )
                continue

            # Remove None values
            org_data = {k: v for k, v in org_data.items() if v is not None}

            with transaction.atomic():
                # Cache the DILA/RPNT-valid domains in the "dpnt" bucket. Computed
                # from a transient instance so it reflects this import's
                # rpnt/website/email. Inside the try: an adresse_messagerie with no
                # "@" raises IndexError, and one malformed row must not abort the
                # whole import.
                dpnt_domains = sorted(
                    org_rpnt_valid_domains(
                        Organization(
                            rpnt=org_data.get("rpnt"),
                            site_internet=org_data.get("site_internet"),
                            adresse_messagerie=org_data.get("adresse_messagerie"),
                        )
                    )
                )

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
                    # Update existing organization. Save the DPNT fields, then merge
                    # the "dpnt" bucket via a row-locked update so a concurrent
                    # superuser edit of another bucket is not clobbered.
                    for field, value in org_data.items():
                        setattr(existing_org, field, value)
                    existing_org.save(
                        update_fields=list(org_data.keys()) + ["updated_at"]
                    )
                    update_proconnect_domains(existing_org, dpnt=dpnt_domains)
                    stats["updated"] += 1
                    logger.debug("Updated organization: %s", existing_org.name)
                elif not existing_org:
                    # Create new organization
                    Organization.objects.create(
                        **org_data, proconnect_domains={"dpnt": dpnt_domains}
                    )
                    stats["created"] += 1
                    logger.debug("Created organization: %s", org_data["name"])
                else:
                    logger.info("Skipped existing organization: %s", org_data["name"])
                    stats["existing"] += 1

                stats["total_processed"] += 1

        except (
            ValueError,
            KeyError,
            IndexError,
            TypeError,
            AttributeError,
            ValidationError,
        ) as e:
            # `item` is why we are here, so it may not be a dict: reading a siret
            # off it must not raise a second time out of the handler.
            siret = (
                item.get("siret", "Unknown") if isinstance(item, dict) else "Unknown"
            )
            error_msg = f"Error processing organization {siret}: {str(e)}"
            logger.error(
                "Error processing organization %s: %s",
                siret,
                str(e),
            )
            stats["errors"] += 1
            stats["errors_details"].append(error_msg)

    # Its own transaction, for the same reason: it must not hold the row locks of
    # every organization the loop above merged.
    with transaction.atomic():
        stats["auto_join"] = _process_auto_join()

    logger.info("DPNT import completed. Stats: %s", stats)
    return stats


def _create_service_subscriptions(operator, service_id, org_ids, valid_services) -> int:
    """Create service subscriptions for organizations and return the count created."""
    existing_sub_org_ids = set(
        ServiceSubscription.objects.filter(
            service_id=service_id, organization_id__in=org_ids
        ).values_list("organization_id", flat=True)
    )
    new_sub_objects = [
        ServiceSubscription(
            operator=operator,
            organization_id=org_id,
            service_id=service_id,
            is_active=True,
        )
        for org_id in org_ids
        if org_id not in existing_sub_org_ids
    ]
    if not new_sub_objects:
        return 0

    # bulk_create with ignore_conflicts returns all objects but only inserts non-conflicting ones.
    # We need to count actual insertions by querying after the fact.
    count_before = ServiceSubscription.objects.filter(
        service_id=service_id, organization_id__in=org_ids
    ).count()

    # NOTE: bulk_create emits no post_save signal, so it bypasses the synchronous
    # ProConnect domains push (see core/signals.py::_sync_proconnect). That is fine
    # here because this only seeds subscription rows, with no metadata["domains"] to
    # contribute; the provider is reconciled by the `proconnect_sync` command, which
    # is NOT currently scheduled in cron.json. If this ever creates *active*
    # proconnect subscriptions with routed domains, call sync_proconnect_provider()
    # for the affected idps afterwards or the provider will silently drift.
    ServiceSubscription.objects.bulk_create(new_sub_objects, ignore_conflicts=True)

    count_after = ServiceSubscription.objects.filter(
        service_id=service_id, organization_id__in=org_ids
    ).count()
    actual_created_count = count_after - count_before

    # Create default entitlements for newly created subscriptions
    # Re-fetch the newly created ones to get their PKs
    if actual_created_count > 0:
        service = valid_services[service_id]
        handler = get_service_handler(service)
        if handler:
            new_org_ids = [obj.organization_id for obj in new_sub_objects]
            created_subs = ServiceSubscription.objects.filter(
                service_id=service_id,
                organization_id__in=new_org_ids,
                operator=operator,
            )
            for sub in created_subs:
                handler.create_default_entitlements(sub)

    return actual_created_count


def _process_auto_join() -> Dict[str, Any]:
    """Process auto_join config for active operators.

    For each active operator with an ``auto_join`` key in its config, this
    function creates ``OperatorOrganizationRole`` and ``ServiceSubscription``
    records for every organization whose type matches the config.

    Must be called inside an existing ``transaction.atomic()`` block.
    """
    stats: Dict[str, int] = {
        "operator_organization_roles_created": 0,
        "service_subscriptions_created": 0,
    }

    operators = Operator.objects.filter(is_active=True, config__has_key="auto_join")

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

        # Bulk create OperatorOrganizationRole — query existing first for stats
        existing_role_org_ids = set(
            OperatorOrganizationRole.objects.filter(
                operator=operator, organization_id__in=org_ids
            ).values_list("organization_id", flat=True)
        )
        new_role_objects = [
            OperatorOrganizationRole(operator=operator, organization_id=org_id)
            for org_id in org_ids
            if org_id not in existing_role_org_ids
        ]
        if new_role_objects:
            OperatorOrganizationRole.objects.bulk_create(
                new_role_objects, ignore_conflicts=True
            )
        stats["operator_organization_roles_created"] += len(new_role_objects)

        # Bulk create ServiceSubscription per valid service
        valid_services = {osc.service_id: osc.service for osc in valid_service_configs}
        for service_id in valid_service_ids:
            created_count = _create_service_subscriptions(
                operator, service_id, org_ids, valid_services
            )
            stats["service_subscriptions_created"] += created_count

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
