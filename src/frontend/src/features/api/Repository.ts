import { SortModel } from "@gouvfr-lasuite/ui-components";
import { fetchAPI } from "./fetchApi";

type PaginatedResponse<T> = {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
};

export type OperatorIdp = {
  id: string;
  name: string;
};

export type Operator = {
  id: string;
  name: string;
  url: string;
  scope: string;
  is_active: boolean;
  config: {
    idps: OperatorIdp[];
  };
};

export enum MailDomainStatus {
  VALID = "valid",
  NEED_EMAIL_SETUP = "need_email_setup",
  INVALID = "invalid",
}

export type Organization = {
  id: string;
  name: string;
  type: string;
  code_postal: string;
  url: string;
  service_subscriptions: ServiceSubscription[];
  population: number;
  departement_code_insee: string;
  epci_libelle: string;
  epci_siren: string | null;
  rpnt: string[];
  mail_domain: string | null;
  mail_domain_status: MailDomainStatus;
  siret: string | null;
  adresse_messagerie: string | null;
  site_internet: string | null;
  telephone: string | null;
  // The org's ProConnect domains, by provenance — "dpnt" (declared on
  // service-public.gouv.fr), "candidates" (generated from the name), "manual"
  // (added by a superuser) — and status — "requested" (awaiting validation),
  // "discarded" (set aside). What is currently live is not a bucket: it is the
  // subscription's routed domains.
  proconnect_domains: {
    requested: string[];
    manual: string[];
    dpnt: string[];
    candidates: string[];
    discarded: string[];
  };
  // The domains the org may route, buckets and discards already resolved by the
  // backend. Offer exactly these — never re-derive them from the buckets here.
  proconnect_routable: string[];
  // Per-idp pre-validation: {idp_id: [domains already in that provider's deployed
  // allowlist]}. An idp present (even with []) means its allowlist is known and a
  // domain missing from it is "not yet pre-validated"; null means unknown. Per-idp
  // because the same domain can be deployed on one provider and pending on another.
  proconnect_prevalidated: Record<string, string[]> | null;
  operator_admins_have_admin_role?: boolean;
};

export type ServiceSubscription = {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  metadata: Record<string, any>;
  created_at: string;
  updated_at: string;
  service?: Service;
  is_active: boolean;
  entitlements: Entitlement[];
  operator_id?: string;
  operator_name?: string;
};

// Input type for creating/updating subscriptions
export type ServiceSubscriptionInput = Partial<
  Omit<ServiceSubscription, "entitlements" | "created_at" | "updated_at">
> & {
  entitlements?: EntitlementInput[];
};

export type Entitlement = {
  type: string;
  config: Record<string, unknown>;
  account_type: string;
  account_id: string;
  id: string;
};

// Input type for creating/updating entitlements via subscription API
export type EntitlementInput = {
  type: string;
  account_type: string;
  config: Record<string, unknown>;
};

export const SERVICE_TYPE_PROCONNECT = "proconnect";
export const SERVICE_TYPE_ADC = "adc";
export const SERVICE_TYPE_ESD = "esd";
export const SERVICE_TYPE_MESSAGES = "messages";
export const SERVICE_TYPE_DRIVE = "drive";
export const SERVICE_TYPE_DOMAINS = "domains";
export const SERVICE_TYPE_BAL = "bal";

// The address channels a BAL commune exposes for administration. Mirrors
// core.services.bal.CHANNELS.
export const BAL_CHANNELS = [
  "channel_api_depot",
  "channel_moissonneur",
  "channel_mesadresses",
  "channel_formulaire",
];

// What serves a domain's website, in the Domains service subscription metadata.
export const WEBSITE_MODE_NONE = "none";
export const WEBSITE_MODE_PARKING = "parking";
export const WEBSITE_MODE_DNS_A = "dns_a";
export const WEBSITE_MODE_DNS_CNAME = "dns_cname";
export const WEBSITE_MODE_REDIRECT_301 = "redirect_301";
export const WEBSITE_MODE_REDIRECT_302 = "redirect_302";

export type DomainWebsite = {
  mode: string;
  // The value the mode points at: an IPv4 address for dns_a, a domain name for
  // dns_cname, an https url for the redirections. Absent for parking and none.
  target?: string;
};

export type DomainWebsiteConfig = Record<string, DomainWebsite>;

// One domain's checks, as returned by the domains-check route. The backend is the
// only validator: everything the modal needs to shape itself comes from here rather
// than from rules restated in TypeScript.
export type DomainCheck = {
  domain: string;
  // The domain's NS records as published, empty when the lookup failed.
  nameservers: string[];
  nameservers_valid: boolean;
  // Why there are no nameservers: "nxdomain", "not_delegated", "timeout",
  // "error". Null when the lookup succeeded.
  error: string | null;
  rpnt_1_2_valid: boolean;
  extension: string;
  // The website modes this domain may use, and the one it falls back to.
  allowed_modes: string[];
  default_mode: string;
};

export type DomainsCheck = {
  expected_nameservers: string[];
  // The modes that carry a "target" value, so the form knows when to show it.
  modes_with_target: string[];
  results: DomainCheck[];
};

export type AccountServiceLinkRole = { scope: Record<string, unknown> };

export type AccountServiceLink = {
  roles: Record<string, AccountServiceLinkRole>;
  service: {
    id: string;
    name: string;
    instance_name: string;
    type: string;
  };
};

export type Account = {
  id: string;
  email: string;
  external_id: string;
  type: string;
  roles: string[];
  service_links: AccountServiceLink[];
};

export type EntitlementDefault = {
  type: string;
  account_type: string;
  config: Record<string, unknown>;
};

export type Service = {
  id: string;
  name: string;
  instance_name: string;
  url: string;
  description: string;
  type: string;
  subscription: ServiceSubscription;
  logo: string | null;
  hidden?: boolean;
  operator_config?: {
    display_priority?: number;
    externally_managed?: boolean;
  } | null;
  can_activate: boolean;
  activation_blocked_reason?: string;
  config?: {
    help_center_url?: string;
    auto_admin_population_threshold?: number;
    idp_id?: string;
  };
  entitlement_defaults?: EntitlementDefault[];
};

export const sortModelToOrdering = (sortModel: SortModel): string => {
  return sortModel
    .map((sort) => {
      if (sort.sort === "asc") return `${sort.field}`;
      if (sort.sort === "desc") return `-${sort.field}`;
      return "";
    })
    .join(",");
};

export const getOperators = async (): Promise<PaginatedResponse<Operator>> => {
  const response = await fetchAPI("operators/?page_size=100");
  const data = (await response.json()) as PaginatedResponse<Operator>;
  return data;
};

export const getOperator = async (operatorId: string): Promise<Operator> => {
  const response = await fetchAPI(`operators/${operatorId}/`);
  const data = (await response.json()) as Operator;
  return data;
};

export type ServiceLight = {
  id: string;
  name: string;
  instance_name: string;
  type: string;
};

export const getOperatorServices = async (
  operatorId: string
): Promise<{ results: ServiceLight[] }> => {
  const response = await fetchAPI(`operators/${operatorId}/services/`);
  const data = (await response.json()) as { results: ServiceLight[] };
  return data;
};

export const getOperatorOrganizations = async (
  operatorId: string,
  params: {
    page?: number;
    search?: string;
    ordering?: string;
    type?: string;
    service?: string;
    // RPNT meta-criterion: "a", "1.a", "2.a", each prefixed with "!" for its negative.
    rpnt?: string;
  }
): Promise<PaginatedResponse<Organization>> => {
  const url = new URL(`/`, window.location.origin);
  Object.entries(params).forEach(([key, value]) => {
    if (value) url.searchParams.append(key, value.toString());
  });
  const response = await fetchAPI(
    `operators/${operatorId}/organizations/` + url.search
  );
  const data = (await response.json()) as PaginatedResponse<Organization>;
  return data;
};

export const getOrganization = async (
  operatorId: string,
  organizationId: string
): Promise<Organization> => {
  const response = await fetchAPI(
    `operators/${operatorId}/organizations/${organizationId}/`
  );
  const data = (await response.json()) as Organization;
  return data;
};

export const updateOperatorOrganizationRole = async (
  operatorId: string,
  organizationId: string,
  data: { operator_admins_have_admin_role: boolean }
): Promise<{ operator_admins_have_admin_role: boolean }> => {
  const response = await fetchAPI(
    `operators/${operatorId}/organizations/${organizationId}/operator-role/`,
    { method: "PATCH", body: JSON.stringify(data) }
  );
  return (await response.json()) as { operator_admins_have_admin_role: boolean };
};

export const updateOrganizationProconnectDomains = async (
  operatorId: string,
  organizationId: string,
  payload: { manual?: string[]; requested?: string[]; discarded?: string[] }
): Promise<Organization["proconnect_domains"]> => {
  const response = await fetchAPI(
    `operators/${operatorId}/organizations/${organizationId}/proconnect-domains/`,
    { method: "PATCH", body: JSON.stringify(payload) }
  );
  return (await response.json()) as Organization["proconnect_domains"];
};

export const checkDomains = async (
  operatorId: string,
  organizationId: string,
  domains: string[]
): Promise<DomainsCheck> => {
  const response = await fetchAPI(
    `operators/${operatorId}/organizations/${organizationId}/domains-check/`,
    { method: "POST", body: JSON.stringify({ domains }) }
  );
  return (await response.json()) as DomainsCheck;
};

export const getOrganizationServices = async (
  operatorId: string,
  organizationId: string
): Promise<PaginatedResponse<Service>> => {
  const response = await fetchAPI(
    `operators/${operatorId}/organizations/${organizationId}/services/`
  );
  const data = (await response.json()) as PaginatedResponse<Service>;
  return data;
};

export const updateOrganizationServiceSubscription = async (
  operatorId: string,
  organizationId: string,
  serviceId: string,
  data: ServiceSubscriptionInput
): Promise<ServiceSubscription> => {
  const response = await fetchAPI(
    `operators/${operatorId}/organizations/${organizationId}/services/${serviceId}/subscription/`,
    {
      method: "PATCH",
      body: JSON.stringify(data),
    }
  );
  const subscription = (await response.json()) as ServiceSubscription;
  return subscription;
};

export const getOrganizationAccounts = async (
  operatorId: string,
  organizationId: string,
  params: {
    page?: number;
    search?: string;
    ordering?: string;
    type?: string;
    role?: string;
  }
): Promise<PaginatedResponse<Account>> => {
  const url = new URL(`/`, window.location.origin);
  Object.entries(params).forEach(([key, value]) => {
    if (value) url.searchParams.append(key, value.toString());
  });
  const response = await fetchAPI(
    `operators/${operatorId}/organizations/${organizationId}/accounts/` +
      url.search
  );
  return (await response.json()) as PaginatedResponse<Account>;
};

export const createOrganizationAccount = async (
  operatorId: string,
  organizationId: string,
  data: { email: string; external_id: string; type: string; roles: string[] }
): Promise<Account> => {
  const response = await fetchAPI(
    `operators/${operatorId}/organizations/${organizationId}/accounts/`,
    {
      method: "POST",
      body: JSON.stringify(data),
    }
  );
  return (await response.json()) as Account;
};

export const updateAccount = async (
  accountId: string,
  data: Partial<Pick<Account, "roles">>
): Promise<Account> => {
  const response = await fetchAPI(`accounts/${accountId}/`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });
  return (await response.json()) as Account;
};

export const deleteAccount = async (accountId: string): Promise<void> => {
  await fetchAPI(`accounts/${accountId}/`, {
    method: "DELETE",
  });
};

export const updateAccountServiceLink = async (
  accountId: string,
  serviceId: string,
  data: { roles: Record<string, { scope?: Record<string, unknown> }> }
): Promise<AccountServiceLink> => {
  const response = await fetchAPI(
    `accounts/${accountId}/services/${serviceId}/`,
    {
      method: "PATCH",
      body: JSON.stringify(data),
    }
  );
  return (await response.json()) as AccountServiceLink;
};

// Metrics types
export type MetricAccount = {
  id: string;
  email: string;
  external_id: string;
  type: string;
};

export type MetricOrganization = {
  id: string;
  name: string;
};

export type Metric = {
  id: number;
  key: string;
  value: string;
  timestamp: string;
  account: MetricAccount | null;
  organization: MetricOrganization;
};

export type MetricsResponse = PaginatedResponse<Metric>;

export type GroupedMetricItem = {
  organization: MetricOrganization;
  value: string;
};

export type GroupedMetricsResponse = PaginatedResponse<GroupedMetricItem> & {
  grouped_by: "organization";
};

export type AggregatedMetric = {
  key: string;
  // IntegerField on AggregatedMetricSerializer, fed from Service.id.
  service_id: number;
  aggregation: "sum" | "avg";
  value: string;
  count: number;
};

export type MetricsOrderBy = "organization" | "value" | "-value";

export type MetricsParams = {
  key: string;
  service: string;
  organizations?: string[];
  accounts?: string[];
  account_type?: string;
  agg?: "sum" | "avg";
  group_by?: "organization";
  order_by?: MetricsOrderBy;
  page?: number;
  page_size?: number;
};

export const getOperatorMetrics = async (
  operatorId: string,
  params: MetricsParams
): Promise<MetricsResponse | GroupedMetricsResponse | AggregatedMetric> => {
  const url = new URL(`/`, window.location.origin);
  url.searchParams.append("key", params.key);
  url.searchParams.append("service", params.service);

  if (params.organizations && params.organizations.length > 0) {
    url.searchParams.append("organizations", params.organizations.join(","));
  }
  if (params.accounts && params.accounts.length > 0) {
    url.searchParams.append("accounts", params.accounts.join(","));
  }
  if (params.account_type) {
    url.searchParams.append("account_type", params.account_type);
  }
  if (params.agg) {
    url.searchParams.append("agg", params.agg);
  }
  if (params.group_by) {
    url.searchParams.append("group_by", params.group_by);
  }
  if (params.order_by) {
    url.searchParams.append("order_by", params.order_by);
  }
  if (params.page) {
    url.searchParams.append("page", params.page.toString());
  }
  if (params.page_size) {
    url.searchParams.append("page_size", params.page_size.toString());
  }

  const response = await fetchAPI(
    `operators/${operatorId}/metrics/` + url.search
  );
  return (await response.json()) as
    | MetricsResponse
    | GroupedMetricsResponse
    | AggregatedMetric;
};

/** The largest page the API will serve (Pagination.max_page_size). */
const EXPORT_PAGE_SIZE = 200;

/**
 * Every row matching the filters, not just the page on screen.
 *
 * The endpoint is paginated with no "all" escape hatch, so this walks the pages
 * and concatenates them. Ordering is what makes that safe: every ordering the
 * API accepts ends on a unique column, so a row cannot move between pages while
 * the walk is in progress.
 */
export const getAllOperatorMetrics = async (
  operatorId: string,
  params: MetricsParams,
  onProgress?: (loaded: number, total: number) => void
): Promise<MetricsResponse | GroupedMetricsResponse | AggregatedMetric> => {
  const first = await getOperatorMetrics(operatorId, {
    ...params,
    page: 1,
    page_size: EXPORT_PAGE_SIZE,
  });

  // An aggregation is a single value, so there is nothing to page through.
  if ("aggregation" in first) {
    return first;
  }

  const total = first.count;
  const results = [...first.results];
  onProgress?.(results.length, total);

  for (let page = 2; results.length < total; page += 1) {
    const next = (await getOperatorMetrics(operatorId, {
      ...params,
      page,
      page_size: EXPORT_PAGE_SIZE,
    })) as MetricsResponse | GroupedMetricsResponse;

    // A page that comes back empty would otherwise spin forever.
    if (next.results.length === 0) {
      break;
    }
    results.push(...(next.results as (typeof results)[number][]));
    onProgress?.(results.length, total);
  }

  return { ...first, results } as MetricsResponse | GroupedMetricsResponse;
};

/**
 * The metric keys this operator actually has data for, for a given service.
 *
 * The dashboard offers only these: a hardcoded list would let a user pick a key
 * that can only ever draw an empty chart.
 */
export const getOperatorMetricKeys = async (
  operatorId: string,
  serviceId: string
): Promise<{ results: string[] }> => {
  const url = new URL(`/`, window.location.origin);
  if (serviceId) {
    url.searchParams.append("service", serviceId);
  }
  const response = await fetchAPI(
    `operators/${operatorId}/metrics/keys/` + url.search
  );
  return (await response.json()) as { results: string[] };
};
