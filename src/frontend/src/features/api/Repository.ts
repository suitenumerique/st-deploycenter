import { SortModel } from "@openfun/cunningham-react";
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
  rpnt: string[];
  mail_domain: string | null;
  mail_domain_status: MailDomainStatus;
  siret: string | null;
  adresse_messagerie: string | null;
  site_internet: string | null;
  telephone: string | null;
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

export type AccountServiceLink = {
  roles: string[];
  scope: Record<string, unknown>;
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

export const orderingToSortModel = (ordering: string): SortModel => {
  return ordering.split(",").map((order) => {
    if (order.startsWith("-")) return { field: order.slice(1), sort: "desc" };
    return { field: order, sort: "asc" };
  });
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

export const deleteOrganizationServiceSubscription = async (
  operatorId: string,
  organizationId: string,
  serviceId: string
): Promise<void> => {
  await fetchAPI(
    `operators/${operatorId}/organizations/${organizationId}/services/${serviceId}/subscription/`,
    {
      method: "DELETE",
    }
  );
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

export const updateEntitlement = async (
  entitlementId: string,
  data: Partial<Entitlement>
): Promise<Entitlement> => {
  const response = await fetchAPI(`entitlements/${entitlementId}/`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });
  const entitlement = (await response.json()) as Entitlement;
  return entitlement;
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
  data: { roles: string[]; scope?: Record<string, unknown> }
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
