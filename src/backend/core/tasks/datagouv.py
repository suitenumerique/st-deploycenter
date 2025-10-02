"""
Upload data to data.gouv.fr
"""

import csv
import gzip
import io
import logging

from django.conf import settings

import requests
from celery import shared_task

from ..models import Metric, Service

logger = logging.getLogger(__name__)


# pylint: disable=invalid-name
def _upload_data_to_data_gouv(dataset_id, resource_id, file_data, filename):
    """Upload public files to data.gouv.fr"""

    if not settings.DATA_GOUV_API_KEY:
        raise ValueError("DATA_GOUV_API_KEY is not set, can't upload to data.gouv.fr")

    # https://guides.data.gouv.fr/guide-data.gouv.fr/readme-1/gerer-un-jeu-de-donnees-par-lapi
    # https://www.data.gouv.fr/datasets/deploiement-des-services-de-lincubateur-des-territoires/
    API = "https://www.data.gouv.fr/api/1"
    API_KEY = settings.DATA_GOUV_API_KEY
    HEADERS = {
        "X-API-KEY": API_KEY,
    }

    response = requests.post(
        API + f"/datasets/{dataset_id}/resources/{resource_id}/upload/",
        files={
            "file": (filename, file_data, "application/gzip"),
        },
        headers=HEADERS,
        timeout=120,
    )

    response.raise_for_status()

    data = response.json()

    if not data["success"]:
        raise ValueError(f"Failed to upload file to data.gouv.fr: {data}")

    return data


@shared_task
def upload_deployment_metrics_dataset():
    """Upload deployment metrics dataset to data.gouv.fr"""

    dataset_id = "68b0a2a1117b75b1b09edc6b"
    resource_id = "8f100b83-73c5-49ce-90ce-03d5c6a1783d"

    data = {
        f"{metric.organization.siret} {metric.service.id}": {
            "type": metric.organization.type,
            "siret": metric.organization.siret,
            "insee": metric.organization.code_insee,
            "population": metric.organization.population,
            "service": metric.service.id,
            "active": 0,
        }
        for metric in Metric.objects.select_related("organization", "service")
        .filter(key="tu", value__gt=0)
        .filter(organization__population__gt=0)
        .exclude(organization__siret__isnull=True)
        .exclude(organization__siret="")
        .filter(service__is_active=True)
        .all()
    }

    logger.info("Produced %s data rows", len(data))

    unique_services = {row["service"] for row in data.values()}
    for service_id in unique_services:
        # Services might have different criteria to define if they are active. For now, we consider yau>0.
        active_sirets = (
            Metric.objects.select_related("organization", "service")
            .filter(service_id=service_id, key="yau", value__gt=0)
            .values_list("organization__siret", flat=True)
        )
        for siret in active_sirets:
            data[f"{siret} {service_id}"]["active"] = 1

    data = list(data.values())

    # Create gzipped CSV in memory
    buffer = io.BytesIO()
    with gzip.GzipFile(
        filename="deploiement-quotidien.csv", fileobj=buffer, mode="wb", compresslevel=9
    ) as gz_file:
        with io.TextIOWrapper(gz_file, encoding="utf-8") as text_file:
            writer = csv.DictWriter(text_file, fieldnames=data[0].keys(), delimiter=";")
            writer.writeheader()
            for row in data:
                writer.writerow(row)

    buffer.seek(0)
    _upload_data_to_data_gouv(
        dataset_id, resource_id, buffer.getvalue(), "deploiement-quotidien.csv.gz"
    )

    return {
        "status": "success",
        "message": f"Uploaded {len(data)} metrics to data.gouv.fr",
    }


@shared_task
def upload_deployment_services_dataset():
    """Upload deployment services dataset to data.gouv.fr"""

    dataset_id = "68b0a2a1117b75b1b09edc6b"
    resource_id = "610560cf-5893-4a53-b4d3-03e17d877e1c"

    services = Service.objects.filter(is_active=True)

    data = [
        {
            "id": service.id,
            "nom": service.name,
            "url": service.url,
            "maturite": service.maturity,
            "date_lancement": service.launch_date,
            "logo_url": f"{settings.API_PUBLIC_URL}servicelogo/{service.id}/"
            if service.logo_svg
            else "",
        }
        for service in services
    ]

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=data[0].keys(), delimiter=";")
    writer.writeheader()
    for row in data:
        writer.writerow(row)

    buffer.seek(0)
    _upload_data_to_data_gouv(
        dataset_id,
        resource_id,
        buffer.getvalue().encode("utf-8"),
        "services-quotidien.csv",
    )

    return {
        "status": "success",
        "message": f"Uploaded {len(data)} services to data.gouv.fr",
    }
