/**
 * The one domain rule kept in the browser, shared by the "add a domain" boxes of
 * the domains and ProConnect modals.
 *
 * Same shape as the backend's check (core/services/domainnames.py): at least two
 * alphanumeric/hyphen labels. The backend 400s on a value that fails it, so catch
 * it here rather than pretending the add worked.
 *
 * Everything else — which website modes a domain may use, whether a target is a
 * usable address or url, RPNT 1.2 — is decided by the backend and read off the
 * domains-check response, so no rule is written twice.
 */
export const DOMAIN_RE =
  /^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+$/;
