# Authentication

Users log in through OpenID Connect (`mozilla-django-oidc`), against ProConnect
in production and Keycloak in development. The authorization code flow lives in
`core/authentication/`: `views.OIDCAuthenticationRequestView` builds the
authorization request, `backends.OIDCAuthenticationBackend` turns the callback
into a `User`.

## Requiring multi-factor authentication

`OIDC_REQUIRE_MFA` is off by default. Turn it on to refuse any login that the
provider did not perform with a second factor:

```shellscript
OIDC_REQUIRE_MFA=True
```

It acts on both legs of the flow, because either one alone proves nothing:

- the authorization request carries an essential `acr` claim restricted to the
  values that include a second factor, which is how
  [ProConnect asks for 2FA](https://partenaires.proconnect.gouv.fr/docs/fournisseur-service/double_authentification).
  Users without a second factor are sent to ProConnect's setup flow;
- the `acr` claim of the returned `id_token` is checked against the same list.
  A request is only a request: this check is what makes the setting a control.

A login that comes back with any other `acr` is refused, logged with the value
received, and the user is redirected to `LOGIN_REDIRECT_URL_FAILURE`.

## Sessions opened before the setting was turned on

Those two checks only run when someone logs in, so they say nothing about the
sessions already open — which last up to `SESSION_COOKIE_AGE` (12 hours) and,
with the cache session engine, cannot be purged without flushing the cache.

`RequireMFAMiddleware` closes that window: it ends any OIDC session whose
recorded `acr` is not in `OIDC_MFA_ACR_VALUES` on its next request, so users
authenticated without a second factor are sent back through the provider as
soon as the setting is on. Narrowing `OIDC_MFA_ACR_VALUES` later has the same
effect on the sessions below the new bar.

The backend records the `acr` in the session at login for the middleware to
read. Sessions opened another way are untouched: a staff member logging into
the Django admin with a password never gets an `acr` claim, and bearer-token
API calls carry no session.

`OIDC_MFA_ACR_VALUES` holds the accepted values, defaulting to ProConnect's
[eIDAS levels](https://partenaires.proconnect.gouv.fr/docs/fournisseur-service/niveaux-eidas)
that carry a factor: `eidas0-mfa`, `eidas1-mfa` (weak second factor), `eidas2`
and `eidas3` (strong). Narrow it to `["eidas2", "eidas3"]` to demand a strong
one. The values are provider-specific: another provider means another list.

While the setting is on, `OIDC_MFA_ACR_VALUES` is the only thing that sets the
assurance level: an `acr_values` in `OIDC_AUTH_REQUEST_EXTRA_PARAMS` (the
development defaults ask for `eidas1`) contradicts the essential claim, so it
is left out of the authorization request. Nothing to change when turning the
setting on or off, in either direction.

One thing to know before turning it on: **set it on a provider that supports
it.** The development Keycloak returns its own `acr` values, so every login is
refused until `OIDC_MFA_ACR_VALUES` matches what it sends. A refused login logs
the value received:

```
Authentication refused, acr claim 'eidas1' is not one of ['eidas0-mfa', ...]
```

## What the setting covers

Password logins are an exemption: a staff member signing into the Django admin
with a password gets a session with no `acr`, and that session is also accepted
by the API through session authentication. OIDC-created users have an unusable
password, so this covers admin-provisioned staff accounts only. Give those
accounts a second factor of their own (`django-otp` or equivalent) if the
requirement is meant to hold for everyone.

## How the API authenticates

Two ways, and neither is OIDC:

- the **session cookie** the UI gets from the login callback, which is where
  the MFA checks above apply;
- the **API keys** partners send as `Authorization: Bearer <key>`, declared per
  viewset (`OperatorExternalManagementApiKeyAuthentication`,
  `ServiceExternalManagementApiKeyAuthentication`) and matched before anything
  else. A few endpoints check their own key in a permission class instead.

`mozilla_django_oidc.contrib.drf.OIDCAuthentication` used to sit first in
`DEFAULT_AUTHENTICATION_CLASSES` and accept a raw ProConnect access token as a
credential. It was removed. It validated a token by asking the provider's
userinfo endpoint, with no audience check, so a token issued to another service
of the federation authenticated here; it carried no `acr` to enforce
`OIDC_REQUIRE_MFA` on; and any bearer credential the API-key classes did not
match fell through to it, sending partner keys to the provider. The UI never
used it: it authenticates with cookies (`credentials: "include"`).

Sending a ProConnect access token to this API therefore returns 401. The
session class is subclassed in `core/authentication/__init__.py` only to keep
DRF answering 401 rather than 403 on unauthenticated requests, which is what
the frontend redirects to the login page on.
