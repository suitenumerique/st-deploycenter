import {
  getOperator,
  getOrganizationServices,
  deleteOrganizationServiceSubscription,
  createOrganizationServiceSubscription,
  getOperatorOrganizations,
} from "@/features/api/Repository";
import { getOrganization } from "@/features/api/Repository";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

export const useOperator = (operatorId: string) => {
  return useQuery({
    queryKey: ["operators", operatorId],
    queryFn: () => getOperator(operatorId),
    enabled: !!operatorId,
  });
};

export const useOrganization = (operatorId: string, organizationId: string) => {
  return useQuery({
    queryKey: ["operators", operatorId, "organizations", organizationId],
    queryFn: () => getOrganization(operatorId, organizationId),
  });
};

export const useOperatorOrganizations = (
  operatorId: string,
  params: Parameters<typeof getOperatorOrganizations>[1]
) => {
  return useQuery({
    queryKey: [
      "operators",
      operatorId,
      "organizations",
      JSON.stringify(params),
    ],
    queryFn: () => getOperatorOrganizations(operatorId, params),
  });
};

export const useOrganizationServices = (operatorId: string, organizationId: string) => {
  return useQuery({
    queryKey: ["operators", operatorId, "organizations", organizationId, "services"],
    queryFn: () => getOrganizationServices(operatorId, organizationId),
  });
};

export const useMutationDeleteOrganizationServiceSubscription = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      operatorId,
      organizationId,
      serviceId,
      subscriptionId,
    }: {
      operatorId: string;
      organizationId: string;
      serviceId: string;
      subscriptionId: string;
    }) => {
      return deleteOrganizationServiceSubscription(
        operatorId,
        organizationId,
        serviceId,
        subscriptionId
      );
    },
    onSuccess: (data, variables) => {
      queryClient.invalidateQueries({
        queryKey: ["organizations", variables.organizationId, "services"],
      });
      queryClient.invalidateQueries({
        queryKey: ["operators"],
      });
    },
  });
};

export const useMutationCreateOrganizationServiceSubscription = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      operatorId,
      organizationId,
      serviceId,
    }: {
      operatorId: string;
      organizationId: string;
      serviceId: string;
    }) => {
      return createOrganizationServiceSubscription(
        operatorId,
        organizationId,
        serviceId
      );
    },
    onSuccess: (data, variables) => {
      queryClient.invalidateQueries({
        queryKey: ["organizations", variables.organizationId, "services"],
      });
      queryClient.invalidateQueries({
        queryKey: ["operators"],
      });
    },
  });
};

export default useOperator;
