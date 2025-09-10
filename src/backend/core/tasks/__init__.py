"""
Core tasks package.

This package contains all Celery tasks for the core application.
"""

# Import DPNT tasks
# Import datagouv tasks
from .datagouv import (
    upload_deployment_metrics_dataset,
    upload_deployment_services_dataset,
)
from .dpnt import download_dpnt_dataset, import_dpnt_dataset

# Import metrics tasks
from .metrics import scrape_all_service_metrics, scrape_service_metrics

__all__ = [
    # DPNT tasks
    "import_dpnt_dataset",
    "download_dpnt_dataset",
    # Metrics tasks
    "scrape_all_service_metrics",
    "scrape_service_metrics",
    # Datagouv tasks
    "upload_deployment_services_dataset",
    "upload_deployment_metrics_dataset",
]
