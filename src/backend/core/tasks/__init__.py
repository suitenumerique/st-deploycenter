"""
Core tasks package.

Every background task of the application, all periodic (see
docs/deployment.md, "Background tasks"). This module is what the worker and
the scheduler import to register them (``DRAMATIQ_AUTODISCOVER_MODULES``), so
every task module must be imported here.
"""

from .datagouv import (
    upload_deployment_adherents_dataset,
    upload_deployment_datasets,
    upload_deployment_metrics_dataset,
    upload_deployment_operators_dataset,
    upload_deployment_services_dataset,
    upload_deployment_subscriptions_dataset,
)
from .dpnt import import_dpnt_dataset
from .maintenance import prune_task_history
from .metrics import scrape_all_service_metrics, scrape_service_metrics
from .proconnect import fetch_proconnect_prevalidated

__all__ = [
    # DPNT tasks
    "import_dpnt_dataset",
    # Metrics tasks
    "scrape_all_service_metrics",
    "scrape_service_metrics",
    # Datagouv tasks
    "upload_deployment_datasets",
    "upload_deployment_services_dataset",
    "upload_deployment_metrics_dataset",
    "upload_deployment_operators_dataset",
    "upload_deployment_subscriptions_dataset",
    "upload_deployment_adherents_dataset",
    # ProConnect tasks
    "fetch_proconnect_prevalidated",
    # Maintenance tasks
    "prune_task_history",
]
