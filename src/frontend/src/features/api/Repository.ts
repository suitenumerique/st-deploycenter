import { SortModel } from "@openfun/cunningham-react";
import { fetchAPI } from "./fetchApi";

type PaginatedResponse<T> = {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
};

export type Operator = {
  id: string;
  name: string;
  url: string;
  scope: string;
  is_active: boolean;
};

type Organization = {
  id: string;
  name: string;
  code_postal: string;
  url: string;
  service_subscriptions: ServiceSubscription[];
  population: number;
  departement_code_insee: string;
  epci_libelle: string;
};

export type ServiceSubscription = {
  id: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  metadata: Record<string, any>;
  created_at: string;
  updated_at: string;
  service?: Service;
};

export type Service = {
  id: string;
  name: string;
  url: string;
  description: string;
  subscription: ServiceSubscription;
  logo: string | null;
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
  const response = await fetchAPI("operators/");
  const data = (await response.json()) as PaginatedResponse<Operator>;
  return data;
};

export const getOperator = async (operatorId: string): Promise<Operator> => {
  const response = await fetchAPI(`operators/${operatorId}/`);
  const data = (await response.json()) as Operator;
  return data;
};

export const getOperatorOrganizations = async (
  operatorId: string,
  params: {
    page?: number;
    search?: string;
    ordering?: string;
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
  organizationId: string
): Promise<Organization> => {
  const response = await fetchAPI(`organizations/${organizationId}/`);
  const data = (await response.json()) as Organization;
  return data;
};

export const getOrganizationServices = async (
  organizationId: string
): Promise<PaginatedResponse<Service>> => {
  const response = await fetchAPI(`organizations/${organizationId}/services/`);
  const data = (await response.json()) as PaginatedResponse<Service>;
  return data;
};

export const createOrganizationServiceSubscription = async (
  organizationId: string,
  serviceId: string
): Promise<ServiceSubscription> => {
  const response = await fetchAPI(
    `organizations/${organizationId}/services/${serviceId}/subscription/`,
    {
      method: "POST",
    }
  );
  const data = (await response.json()) as ServiceSubscription;
  return data;
};

export const deleteOrganizationServiceSubscription = async (
  organizationId: string,
  serviceId: string,
  subscriptionId: string
): Promise<void> => {
  await fetchAPI(
    `organizations/${organizationId}/services/${serviceId}/subscription/${subscriptionId}/`,
    {
      method: "DELETE",
    }
  );
};
