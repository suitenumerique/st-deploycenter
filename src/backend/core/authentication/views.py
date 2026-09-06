"""Authentication Views for the People core app."""

import json
import logging
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import auth
from django.core.exceptions import SuspiciousOperation
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils import crypto

from mozilla_django_oidc.utils import (
    absolutify,
)
from mozilla_django_oidc.views import (
    OIDCAuthenticationRequestView as MozillaOIDCAuthenticationRequestView,
)
from mozilla_django_oidc.views import (
    OIDCLogoutView as MozillaOIDCOIDCLogoutView,
)

logger = logging.getLogger(__name__)


class OIDCAuthenticationRequestView(MozillaOIDCAuthenticationRequestView):
    """Custom authentication request view.

    Asks the provider for multi-factor authentication when OIDC_REQUIRE_MFA is
    on. The request alone does not enforce anything: the acr value that comes
    back is checked by the authentication backend.
    """

    def get_extra_params(self, request):
        """Add the essential "acr" claim request expected by ProConnect."""

        # Copied: the parent returns the OIDC_AUTH_REQUEST_EXTRA_PARAMS setting
        # itself, and writing to it would leak into every later request.
        extra_params = dict(super().get_extra_params(request))

        if settings.OIDC_REQUIRE_MFA:
            # An acr_values asking for a level without a second factor
            # contradicts the essential claim below, and which one the provider
            # honours is up to it. The claim is what ProConnect documents for
            # 2FA, so it is the one we keep.
            extra_params.pop("acr_values", None)
            extra_params["claims"] = self.build_claims_param(extra_params.get("claims"))

        return extra_params

    @staticmethod
    def build_claims_param(configured):
        """Add the acr claim request to the claims already configured, if any.

        A claims parameter set in OIDC_AUTH_REQUEST_EXTRA_PARAMS asks the
        provider for other claims; only the acr entry is ours to add.
        """

        claims = configured if isinstance(configured, dict) else {}

        if isinstance(configured, str):
            try:
                decoded = json.loads(configured)
            except ValueError:
                decoded = None

            # Anything that is not a JSON object ("[]", "null", a number) is
            # unusable here, and would break the login route further down.
            if isinstance(decoded, dict):
                claims = decoded
            else:
                logger.error(
                    "Ignoring the claims of OIDC_AUTH_REQUEST_EXTRA_PARAMS, "
                    "not a JSON object"
                )

        id_token_claims = claims.get("id_token")

        return json.dumps(
            {
                **claims,
                "id_token": {
                    **(id_token_claims if isinstance(id_token_claims, dict) else {}),
                    "acr": {
                        "essential": True,
                        "values": settings.OIDC_MFA_ACR_VALUES,
                    },
                },
            }
        )


class OIDCLogoutView(MozillaOIDCOIDCLogoutView):
    """Custom logout view for handling OpenID Connect (OIDC) logout flow.

    Adds support for handling logout callbacks from the identity provider (OP)
    by initiating the logout flow if the user has an active session.

    The Django session is retained during the logout process to persist the 'state' OIDC parameter.
    This parameter is crucial for maintaining the integrity of the logout flow between this call
    and the subsequent callback.
    """

    @staticmethod
    def persist_state(request, state):
        """Persist the given 'state' parameter in the session's 'oidc_states' dictionary

        This method is used to store the OIDC state parameter in the session, according to the
        structure expected by Mozilla Django OIDC's 'add_state_and_verifier_and_nonce_to_session'
        utility function.
        """

        if "oidc_states" not in request.session or not isinstance(
            request.session["oidc_states"], dict
        ):
            request.session["oidc_states"] = {}

        request.session["oidc_states"][state] = {}
        request.session.save()

    def construct_oidc_logout_url(self, request):
        """Create the redirect URL for interfacing with the OIDC provider.

        Retrieves the necessary parameters from the session and constructs the URL
        required to initiate logout with the OpenID Connect provider.

        If no ID token is found in the session, the logout flow will not be initiated,
        and the method will return the default redirect URL.

        The 'state' parameter is generated randomly and persisted in the session to ensure
        its integrity during the subsequent callback.
        """

        oidc_logout_endpoint = self.get_settings("OIDC_OP_LOGOUT_ENDPOINT")

        if not oidc_logout_endpoint:
            return self.redirect_url

        reverse_url = reverse("oidc_logout_callback")
        id_token = request.session.get("oidc_id_token", None)

        if not id_token:
            return self.redirect_url

        query = {
            "id_token_hint": id_token,
            "state": crypto.get_random_string(self.get_settings("OIDC_STATE_SIZE", 32)),
            "post_logout_redirect_uri": absolutify(request, reverse_url),
        }

        self.persist_state(request, query["state"])

        return f"{oidc_logout_endpoint}?{urlencode(query)}"

    def post(self, request):
        """Handle user logout.

        If the user is not authenticated, redirects to the default logout URL.
        Otherwise, constructs the OIDC logout URL and redirects the user to start
        the logout process.

        If the user is redirected to the default logout URL, ensure her Django session
        is terminated.
        """

        logout_url = self.redirect_url

        if request.user.is_authenticated:
            logout_url = self.construct_oidc_logout_url(request)

        # If the user is not redirected to the OIDC provider, ensure logout
        if logout_url == self.redirect_url:
            auth.logout(request)

        return HttpResponseRedirect(logout_url)


class OIDCLogoutCallbackView(MozillaOIDCOIDCLogoutView):
    """Custom view for handling the logout callback from the OpenID Connect (OIDC) provider.

    Handles the callback after logout from the identity provider (OP).
    Verifies the state parameter and performs necessary logout actions.

    The Django session is maintained during the logout process to ensure the integrity
    of the logout flow initiated in the previous step.
    """

    http_method_names = ["get"]

    def get(self, request):
        """Handle the logout callback.

        If the user is not authenticated, redirects to the default logout URL.
        Otherwise, verifies the state parameter and performs necessary logout actions.
        """

        if not request.user.is_authenticated:
            return HttpResponseRedirect(self.redirect_url)

        state = request.GET.get("state")

        if state not in request.session.get("oidc_states", {}):
            msg = "OIDC callback state not found in session `oidc_states`!"
            raise SuspiciousOperation(msg)

        del request.session["oidc_states"][state]
        request.session.save()

        auth.logout(request)

        return HttpResponseRedirect(self.redirect_url)
