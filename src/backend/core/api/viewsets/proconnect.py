"""API route serving the ProConnect api-partenaires allowlist YAML."""

import rest_framework as drf
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.renderers import BaseRenderer

from core.api import permissions
from core.services.proconnect import (
    build_proconnect_allowlist,
    render_proconnect_allowlist_yaml,
)


class PlainTextRenderer(BaseRenderer):
    """Render already-serialized text as ``text/plain``."""

    media_type = "text/plain"
    format = "txt"
    charset = "utf-8"

    def render(self, data, accepted_media_type=None, renderer_context=None):
        if isinstance(data, bytes):
            return data
        if isinstance(data, dict) and "detail" in data:
            # DRF error payload: render the message, not the dict's repr.
            data = data["detail"]
        return str(data).encode(self.charset)


class ProConnectAllowlistView(drf.views.APIView):
    """Serve the ``oidc_providers`` allowlist as text/plain YAML.

    One entry per ``type=proconnect`` provider; ``allowed_attached_email_domains``
    is the union of each in-scope organization's authorized domains (manual + dpnt
    + candidates + routed), with a ``# Source: ... | <Service-Public URL>`` comment
    per domain.

    Access: ``Authorization: Bearer <PROCONNECT_ALLOWLIST_VIEW_API_KEY>``, always.
    An unset key closes the route rather than opening it.

    Built on every request. It is a full-DB scan, but the caller is a key holder
    fetching it to open a PR, not traffic — and a cache in front of it only bought
    staleness the reader could not see.
    """

    # Same static-key permission as the other key-guarded routes.
    authentication_classes = []
    permission_classes = [permissions.ProConnectAllowlistApiKeyPermission]
    renderer_classes = [PlainTextRenderer]

    @extend_schema(
        # Explicit: the default derives it from the ".yaml" path, and a dot in an
        # operationId breaks generated clients.
        operation_id="proconnect_oidc_providers_retrieve",
        tags=["proconnect"],
        responses={
            200: OpenApiResponse(
                description="The oidc_providers allowlist as text/plain YAML."
            ),
            403: OpenApiResponse(description="Missing or invalid allowlist API key."),
        },
        description=(
            "Return the ProConnect api-partenaires oidc_providers allowlist, "
            "generated from DB data, as text/plain YAML. Requires "
            "'Authorization: Bearer <PROCONNECT_ALLOWLIST_VIEW_API_KEY>'; the "
            "route is closed while that setting is empty."
        ),
    )
    def get(self, request):
        """GET /api/v1.0/proconnect/oidc_providers.yaml"""
        return drf.response.Response(
            render_proconnect_allowlist_yaml(build_proconnect_allowlist())
        )
