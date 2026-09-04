"""Domains API viewsets."""

from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.settings import api_settings
from rest_framework.views import APIView

from core.api import permissions
from core.authentication import OperatorExternalManagementApiKeyAuthentication
from core.services import domainnames
from core.services import domains as domains_service


# pylint: disable=abstract-method
class DomainRecordSerializer(serializers.Serializer):
    """One DNS record to publish. Documentation/schema only."""

    prefix = serializers.CharField(allow_blank=True)
    type = serializers.CharField()
    value = serializers.CharField()


# pylint: disable=abstract-method
class DomainExportEntrySerializer(serializers.Serializer):
    """One exported domain. Documentation/schema only."""

    domain = serializers.CharField()
    website = serializers.DictField()
    records = DomainRecordSerializer(many=True)
    updated_at = serializers.DateTimeField()
    organization = serializers.DictField()
    operator = serializers.DictField()


# pylint: disable=abstract-method
class DomainExportSerializer(serializers.Serializer):
    """The domains export payload. Documentation/schema only."""

    count = serializers.IntegerField()
    results = DomainExportEntrySerializer(many=True)


class DomainListView(APIView):
    """Return every domain declared through the ``domains`` service.

    Read-only export for external jobs (parking pages, zone generation): one entry
    per domain of an *active* domains subscription, with what we serve for it
    (``website``), the DNS records to publish for it (``records``), the organization
    data a page needs and the operator managing it.

    Everything in one response, unfiltered and unpaginated: the point is a single
    snapshot per run, out of a single query, and a consumer that only wants the
    parking pages filters on ``website["mode"]`` itself. Access requires
    ``Authorization: Bearer <DOMAINS_API_KEY>``; when that setting is empty the route
    is closed.
    """

    authentication_classes = []
    permission_classes = [permissions.DomainsApiKeyPermission]

    @extend_schema(
        operation_id="domains_list",
        tags=["domains"],
        responses={200: DomainExportSerializer},
        description=(
            "List the domains declared by organizations through the domains "
            "service. Requires 'Authorization: Bearer <DOMAINS_API_KEY>'."
        ),
    )
    def get(self, request):
        """GET /api/v1.0/domains/"""
        results = domains_service.export_domains()
        return Response({"count": len(results), "results": results})


# pylint: disable=abstract-method
class DomainCheckRequestSerializer(serializers.Serializer):
    """The domains to check."""

    # Blanks allowed: the modal checks the list as typed, and normalization below
    # drops what is not a domain yet.
    domains = serializers.ListField(
        child=serializers.CharField(allow_blank=True),
        allow_empty=True,
        max_length=domainnames.MAX_DOMAINS,
    )


# pylint: disable=abstract-method
class DomainCheckEntrySerializer(serializers.Serializer):
    """One checked domain. Documentation/schema only."""

    domain = serializers.CharField()
    nameservers = serializers.ListField(child=serializers.CharField())
    nameservers_valid = serializers.BooleanField()
    error = serializers.CharField(allow_null=True)
    rpnt_1_2_valid = serializers.BooleanField()
    extension = serializers.CharField()
    allowed_modes = serializers.ListField(child=serializers.CharField())
    default_mode = serializers.CharField()


# pylint: disable=abstract-method
class DomainCheckSerializer(serializers.Serializer):
    """The domains check payload. Documentation/schema only."""

    expected_nameservers = serializers.ListField(child=serializers.CharField())
    modes_with_target = serializers.ListField(child=serializers.CharField())
    results = DomainCheckEntrySerializer(many=True)


class DomainCheckView(APIView):
    """Check the DNS delegation and the RPNT 1.2 conformance of domains.

    POST /api/v1.0/operators/<operator_id>/organizations/<organization_id>/domains-check/

    Body: ``{"domains": ["exemple.fr", …]}``. For each domain, resolves its NS
    records from the DNS root and compares them with the nameservers we expect, and
    checks its extension against the RPNT 1.2 list. Read-only: it writes nothing and
    the domains do not have to be declared yet, so the modal can check what the user
    is about to save.

    The lookups are live DNS, so a call takes as long as the slowest domain (bounded
    by ``core.services.dns.BATCH_TIMEOUT``).
    """

    authentication_classes = [
        OperatorExternalManagementApiKeyAuthentication,
    ] + list(api_settings.DEFAULT_AUTHENTICATION_CLASSES)
    permission_classes = [
        permissions.IsAuthenticatedWithAnyMethod,
        permissions.OperatorAndOrganizationAccessPermission,
    ]

    @extend_schema(
        operation_id="domains_check",
        tags=["domains"],
        request=DomainCheckRequestSerializer,
        responses={200: DomainCheckSerializer},
        description=(
            "Check the DNS delegation and the RPNT 1.2 conformance of a list of "
            "domains for an organization."
        ),
    )
    def post(self, request, *args, **kwargs):
        """POST /api/v1.0/operators/<id>/organizations/<id>/domains-check/"""
        payload = DomainCheckRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)

        # Normalize rather than reject: the modal checks what the user typed, and a
        # half-typed domain should read as "not checked", not as a 400.
        domains = domainnames.normalize_domains(payload.validated_data["domains"])
        return Response(
            {
                "expected_nameservers": domains_service.expected_nameservers(),
                # Which modes need a "target" field: shape the form here rather than
                # restating the rule in the frontend.
                "modes_with_target": list(domains_service.MODES_WITH_TARGET),
                "results": domains_service.check_domains(domains),
            }
        )
