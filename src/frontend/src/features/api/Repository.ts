import { fetchAPI } from "./fetchApi";

type PaginatedResponse<T> = {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
};

type Operator = {
  id: string;
  name: string;
  url: string;
  scope: string;
  is_active: boolean;
};

type Organization = {
  id: string;
  name: string;
  url: string;
};

export type ServiceSubscription = {
  id: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  metadata: Record<string, any>;
  created_at: string;
  updated_at: string;
};

export type Service = {
  id: string;
  name: string;
  url: string;
  description: string;
  subscription: ServiceSubscription;
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
  operatorId: string
): Promise<PaginatedResponse<Organization>> => {
  const response = await fetchAPI(`operators/${operatorId}/organizations/`);
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
