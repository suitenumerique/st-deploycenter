"""
API endpoints for Organization model.
"""

import logging
from collections.abc import Mapping

from django.contrib.admin.models import CHANGE, LogEntry
from django.db.models import Prefetch

from drf_spectacular.utils import extend_schema
from rest_framework import filters, viewsets
from rest_framework import serializers as drf_serializers
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.settings import api_settings

from core import models
from core.authentication import OperatorExternalManagementApiKeyAuthentication
from core.services import domainnames
from core.services import proconnect as proconnect_service
from core.webhooks import send_domain_requested_webhooks

from .. import permissions, serializers

logger = logging.getLogger(__name__)


class OperatorOrganizationViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for Organization model nested in Operator model.

    GET /api/v1.0/operators/<operator_id>/organizations/
        Return the list of organizations for the given operator based on the user's permissions.
        Supports both user authentication and external API key authentication.
    """

    queryset = models.Organization.objects.all()
    serializer_class = serializers.OrganizationSerializer
    authentication_classes = [
        OperatorExternalManagementApiKeyAuthentication,
    ] + list(api_settings.DEFAULT_AUTHENTICATION_CLASSES)
    permission_classes = [
        permissions.IsAuthenticatedWithAnyMethod,
        permissions.OperatorAccessPermission,
    ]
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ["name", "departement_code_insee", "epci_libelle"]

    def get_queryset(self):
        operator_id = self.kwargs["operator_id"]
        subscriptions_queryset = models.ServiceSubscription.objects.filter(
            operator=operator_id
        ).select_related("service", "operator")
        operator_roles_queryset = models.OperatorOrganizationRole.objects.filter(
            operator_id=operator_id
        )

        queryset = (
            models.Organization.objects.filter(operators__id=operator_id)
            .prefetch_related(
                Prefetch("service_subscriptions", queryset=subscriptions_queryset),
                Prefetch(
                    "operator_roles",
                    queryset=operator_roles_queryset,
                    to_attr="prefetched_operator_roles",
                ),
            )
            .all()
        )

        # Filter by type if provided
        if self.request.query_params.get("type"):
            type_filter = self.request.query_params.get("type")
            queryset = queryset.filter(type=type_filter)

        # Filter by service if provided (organizations with active subscription to this service)
        if self.request.query_params.get("service"):
            service_filter = self.request.query_params.get("service")
            queryset = queryset.filter(
                service_subscriptions__service_id=service_filter,
                service_subscriptions__operator_id=self.kwargs["operator_id"],
                service_subscriptions__is_active=True,
            )

        if self.request.query_params.get("search"):
            search_query = self.request.query_params.get("search")

            # Use ILIKE for partial word matching with accent-insensitive search
            # Also search by SIRET and SIREN (exact match for both)
            queryset = queryset.extra(
                where=[
                    """
                    unaccent_immutable(name) ILIKE unaccent_immutable(%s) OR
                    unaccent_immutable(departement_code_insee) ILIKE unaccent_immutable(%s) OR
                    unaccent_immutable(epci_libelle) ILIKE unaccent_immutable(%s) OR
                    siret = %s OR
                    code_postal = %s OR
                    siren = %s
                    """
                ],
                params=[
                    f"%{search_query}%",
                    f"%{search_query}%",
                    f"%{search_query}%",
                    search_query,
                    search_query,
                    search_query,
                ],
            )

            # Order by match priority: SIRET first, then SIREN (both exact matches),
            # then name, then departement_code_insee, then epci_libelle
            queryset = queryset.extra(
                select={
                    "match_priority": """
                        CASE 
                            WHEN siret = %s THEN 1
                            WHEN siren = %s THEN 2
                            WHEN code_postal = %s THEN 3
                            WHEN unaccent_immutable(name) ILIKE unaccent_immutable(%s) THEN 4
                            WHEN unaccent_immutable(departement_code_insee) ILIKE unaccent_immutable(%s) THEN 5
                            WHEN unaccent_immutable(epci_libelle) ILIKE unaccent_immutable(%s) THEN 6
                            ELSE 6
                        END
                    """
                },
                select_params=[
                    search_query,
                    search_query,
                    search_query,
                    f"%{search_query}%",
                    f"%{search_query}%",
                    f"%{search_query}%",
                ],
                order_by=["match_priority", "name"],
            )
        return queryset

    def get_serializer_context(self):
        """Precompute the operator's prevalidated ProConnect allowlists once (not per org).

        ``{idp_id: frozenset(domains)}`` for each of the operator's providers whose
        allowlist we know. Feeds
        ``OrganizationSerializer.proconnect_prevalidated``, which intersects it with
        each organization's own domains — without an N+1 of cache reads.
        """
        context = super().get_serializer_context()
        context["proconnect_prevalidated_allowlists"] = (
            proconnect_service.operator_prevalidated_allowlists(
                self.kwargs.get("operator_id")
            )
        )
        return context

    @action(detail=True, methods=["patch"], url_path="operator-role")
    def operator_role(self, request, *args, **kwargs):
        """Update the OperatorOrganizationRole settings for this org+operator."""
        organization = self.get_object()
        operator_id = self.kwargs["operator_id"]

        role = models.OperatorOrganizationRole.objects.filter(
            operator_id=operator_id, organization=organization
        ).first()
        if not role:
            logger.warning(
                "operator_role: no role found for org=%s operator=%s",
                organization.pk,
                operator_id,
            )
            return Response(
                {"detail": "No operator role found for this organization."},
                status=404,
            )

        if "operator_admins_have_admin_role" in request.data:
            value = request.data["operator_admins_have_admin_role"]
            if not isinstance(value, bool):
                raise drf_serializers.ValidationError(
                    {"operator_admins_have_admin_role": "Must be a boolean."}
                )
            previous = role.operator_admins_have_admin_role
            role.operator_admins_have_admin_role = value
            role.save(update_fields=["operator_admins_have_admin_role", "updated_at"])
            logger.info(
                "operator_role: toggled operator_admins_have_admin_role "
                "%s→%s for org=%s operator=%s",
                previous,
                value,
                organization.pk,
                operator_id,
            )

        return Response(
            {"operator_admins_have_admin_role": role.operator_admins_have_admin_role}
        )

    @staticmethod
    def _normalize_domains(value, field):
        """Validate/normalize a list of domain strings (lowercase, deduped, sorted)."""
        if not isinstance(value, list) or not all(isinstance(d, str) for d in value):
            raise drf_serializers.ValidationError(
                {field: "Must be a list of domain strings."}
            )
        # Capped before normalization, so an oversized bucket never reaches the
        # row-locked write or the public allowlist build.
        if len(value) > domainnames.MAX_DOMAINS:
            raise drf_serializers.ValidationError(
                {field: f"Too many domains (max {domainnames.MAX_DOMAINS})."}
            )
        # Reject with the same rule the storage layer applies. Anything it would
        # refuse must 400 here: normalize_domains() drops it silently otherwise,
        # and the caller gets a 200 with its domain quietly missing.
        invalid = domainnames.invalid_domains(value)
        if invalid:
            raise drf_serializers.ValidationError(
                {field: f"Not valid domain name(s): {', '.join(invalid)}."}
            )
        return domainnames.normalize_domains(value)

    @extend_schema(
        request=serializers.ProConnectDomainsUpdateSerializer,
        # The action returns the buckets, not an Organization (the viewset's
        # serializer_class, which drf-spectacular would infer).
        responses={200: serializers.ProConnectDomainsSerializer},
    )
    @action(detail=True, methods=["patch"], url_path="proconnect-domains")
    def proconnect_domains(self, request, *args, **kwargs):
        """Update the organization's ProConnect domain buckets.

        Body may contain "manual", "requested" and/or "discarded" lists (partial):
        - "requested": any operator member — domains requested for a superuser to
          validate (i.e. move to "manual").
        - "manual" / "discarded": superuser only.

        The system-managed buckets ("dpnt", "candidates") are preserved.
        Each change is recorded as an admin LogEntry on the organization.
        """
        if not isinstance(request.data, Mapping):
            # A list/string body would blow up in the field lookups below.
            return Response(
                {"detail": "Expected an object with domain bucket lists."},
                status=400,
            )

        organization = self.get_object()
        # request.user may be None for external-API-key auth (no superuser powers).
        is_superuser = bool(getattr(request.user, "is_superuser", False))

        # "requested" is open to any operator member; the rest are superuser-only.
        superuser_fields = {"manual", "discarded"} & set(request.data)
        if superuser_fields and not is_superuser:
            return Response(
                {"detail": "Only superusers can edit validated/discarded domains."},
                status=403,
            )

        overrides = {
            field: self._normalize_domains(request.data[field], field)
            for field in ("manual", "requested", "discarded")
            if field in request.data
        }
        # Row-locked merge: never clobber a concurrent cron write of another bucket.
        previous, new_value = proconnect_service.update_proconnect_domains(
            organization, **overrides
        )

        self._log_domain_changes(request, organization, previous, new_value)

        # Notify (statically-configured webhooks) about newly requested domains.
        added_requested = sorted(
            set(new_value["requested"]) - set(previous["requested"])
        )
        if added_requested:
            # Sent inline: there is no celery worker deployed (see Procfile), so
            # queueing this would mean never sending it. Each endpoint carries its
            # own timeout and WebhookClient swallows per-endpoint failures, so the
            # blast radius on this request is bounded.
            operator = models.Operator.objects.filter(
                id=self.kwargs.get("operator_id")
            ).first()
            send_domain_requested_webhooks(
                organization, operator, request.user, added_requested
            )

        return Response(new_value)

    @staticmethod
    def _log_domain_changes(request, organization, previous, new_value):
        """Record an admin LogEntry per added/removed domain (viewable in org history)."""
        messages = []
        for bucket in ("manual", "requested", "discarded"):
            before, after = set(previous[bucket]), set(new_value[bucket])
            for domain in sorted(after - before):
                messages.append(f"added {domain} to {bucket}")
            for domain in sorted(before - after):
                messages.append(f"removed {domain} from {bucket}")
        if not messages:
            return

        change_message = "ProConnect domains: " + "; ".join(messages)
        user_id = getattr(request.user, "pk", None)
        logger.info(
            "%s for org=%s by user=%s", change_message, organization.pk, user_id
        )
        # An admin LogEntry needs a user; skip it for external-API-key (no user).
        if user_id is None:
            return
        LogEntry.objects.log_actions(
            user_id,
            [organization],
            CHANGE,
            change_message=change_message,
            single_object=True,
        )
