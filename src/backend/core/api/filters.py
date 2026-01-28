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
        """Filter accounts that contain the given role in their JSON roles array."""
        return queryset.filter(roles__contains=[value])
