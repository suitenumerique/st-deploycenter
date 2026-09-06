"""Authentication Backends for the deploycenter core app."""

import logging

from django.conf import settings
from django.core.exceptions import SuspiciousOperation
from django.utils.translation import gettext_lazy as _

import requests
from mozilla_django_oidc.auth import (
    OIDCAuthenticationBackend as MozillaOIDCAuthenticationBackend,
)

from core.models import (
    DuplicateEmailError,
    User,
)

logger = logging.getLogger(__name__)

# Session key holding the acr claim a session was authenticated with, so that
# RequireMFAMiddleware can tell an already opened session apart from one that
# went through a second factor.
MFA_ACR_SESSION_KEY = "oidc_mfa_acr"


class OIDCAuthenticationBackend(MozillaOIDCAuthenticationBackend):
    """Custom OpenID Connect (OIDC) Authentication Backend.

    This class overrides the default OIDC Authentication Backend to accommodate differences
    in the User and Identity models, and handles signed and/or encrypted UserInfo response.
    """

    def get_userinfo(self, access_token, id_token, payload):
        """Return user details dictionary.

        Parameters:
        - access_token (str): The access token.
        - id_token (str): The id token (unused).
        - payload (dict): The token payload (unused).

        Note: The id_token and payload parameters are unused in this implementation,
        but were kept to preserve base method signature.

        Note: It handles signed and/or encrypted UserInfo Response. It is required by
        Agent Connect, which follows the OIDC standard. It forces us to override the
        base method, which deal with 'application/json' response.

        Returns:
        - dict: User details dictionary obtained from the OpenID Connect user endpoint.
        """

        user_response = requests.get(
            self.OIDC_OP_USER_ENDPOINT,
            headers={"Authorization": f"Bearer {access_token}"},
            verify=self.get_settings("OIDC_VERIFY_SSL", True),
            timeout=self.get_settings("OIDC_TIMEOUT", None),
            proxies=self.get_settings("OIDC_PROXY", None),
        )
        user_response.raise_for_status()

        try:
            userinfo = user_response.json()
        except ValueError:
            try:
                userinfo = self.verify_token(user_response.text)
            except Exception as e:
                raise SuspiciousOperation(
                    _("Invalid response format or token verification failed")
                ) from e

        return userinfo

    def verify_claims(self, claims):
        """
        Verify the presence of essential claims and the "sub" (which is mandatory as defined
        by the OIDC specification) to decide if authentication should be allowed.
        """
        essential_claims = settings.USER_OIDC_ESSENTIAL_CLAIMS
        missing_claims = [claim for claim in essential_claims if claim not in claims]

        if missing_claims:
            logger.error("Missing essential claims: %s", missing_claims)
            return False

        return True

    def verify_mfa(self, payload):
        """Check that the provider actually performed multi-factor authentication.

        Asking for it in the authorization request is only a request: the "acr"
        claim returned in the id_token is what proves it happened, so it has to
        be checked here.

        The payload is the verified id_token claims. It is None when the token
        did not come from the code flow, i.e. for the bearer tokens accepted by
        the DRF authentication class: those are refused outright, see below.
        """
        if not settings.OIDC_REQUIRE_MFA:
            return

        if payload is None:
            # A bearer token is validated by calling the userinfo endpoint,
            # which says nothing about how the user authenticated, and carries
            # no acr claim to check. It could have been issued to any other
            # service of the federation, at any assurance level, so accepting
            # it here would be a way around the requirement.
            logger.error(
                "Authentication refused, a token with no id_token cannot prove "
                "multi-factor authentication"
            )
            raise SuspiciousOperation(
                _("Multi-factor authentication is required to access this service.")
            )

        acr = payload.get("acr")

        if acr not in settings.OIDC_MFA_ACR_VALUES:
            logger.error(
                "Authentication refused, acr claim %r is not one of %s",
                acr,
                settings.OIDC_MFA_ACR_VALUES,
            )
            raise SuspiciousOperation(
                _("Multi-factor authentication is required to access this service.")
            )

        # Remember it for the whole session: the check above only happens on
        # login, RequireMFAMiddleware relies on this to close the sessions that
        # were opened before the setting was turned on. auth.login() cycles the
        # session key after this but keeps its content.
        request = getattr(self, "request", None)
        if request is not None and hasattr(request, "session"):
            request.session[MFA_ACR_SESSION_KEY] = acr

    def get_or_create_user(self, access_token, id_token, payload):
        """Return a User based on userinfo. Create a new user if no match is found."""

        self.verify_mfa(payload)

        user_info = self.get_userinfo(access_token, id_token, payload)

        if not self.verify_claims(user_info):
            raise SuspiciousOperation("Claims verification failed.")

        sub = user_info["sub"]
        email = user_info.get("email")

        # Get user's full name from OIDC fields defined in settings
        full_name = self.compute_full_name(user_info)

        claims = {"email": email, "full_name": full_name}

        try:
            user = User.objects.get_user_by_sub_or_email(sub, email)
        except DuplicateEmailError as err:
            raise SuspiciousOperation(err.message) from err

        if user:
            if not user.is_active:
                raise SuspiciousOperation(_("User account is disabled"))
            # Update sub if user doesn't have one (for passwordless users created in admin)
            if not user.sub:
                claims["sub"] = sub
            self.update_user_if_needed(user, claims)

        elif self.should_create_user(email):
            user = User.objects.create(sub=sub, password="!", **claims)  # noqa: S106

        if user:
            return user

        return None

    def compute_full_name(self, user_info):
        """Compute user's full name based on OIDC fields in settings."""
        name_fields = settings.USER_OIDC_FIELDS_TO_FULLNAME
        full_name = " ".join(
            user_info[field] for field in name_fields if user_info.get(field)
        )
        return full_name or None

    def update_user_if_needed(self, user, claims):
        """Update user claims if they have changed."""
        has_changed = any(
            value and value != getattr(user, key) for key, value in claims.items()
        )
        if has_changed:
            updated_claims = {key: value for key, value in claims.items() if value}
            self.UserModel.objects.filter(id=user.id).update(**updated_claims)
            # Refresh user instance to reflect changes
            user.refresh_from_db()

    def should_create_user(self, email):
        """Check if a user should be created based on the email address."""

        if not email:
            return False

        # With this setting, we always create a user locally
        if self.get_settings("OIDC_CREATE_USER", True):
            return True

        # Don't create a user locally
        return False
