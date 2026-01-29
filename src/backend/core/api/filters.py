"""API filters for deploycenter core application."""

import django_filters

from core import models


class AccountFilter(django_filters.FilterSet):
    """Filter accounts by type and role."""

    type = django_filters.CharFilter(field_name="type")
    role = django_filters.CharFilter(method="filter_by_role")

    class Meta:
        model = models.Account
        fields = ["type"]

    def filter_by_role(self, queryset, _name, value):
        """Filter accounts by role with scope prefix.

        Formats:
        - org.<role>             → global/organization-level role
        - service.<id>.<role>    → service-specific role
        """
        if value.startswith("org."):
            role = value[4:]
            return queryset.filter(roles__contains=[role])

        if value.startswith("service."):
            parts = value.split(".", 2)
            if len(parts) == 3:
                service_id, role = parts[1], parts[2]
                return queryset.filter(
                    service_links__service_id=service_id,
                    service_links__roles__contains=[role],
                ).distinct()

        return queryset.none()
