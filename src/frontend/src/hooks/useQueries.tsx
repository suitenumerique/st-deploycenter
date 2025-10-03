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

export const useOrganization = (organizationId: string) => {
  return useQuery({
    queryKey: ["organizations", organizationId],
    queryFn: () => getOrganization(organizationId),
  });
};

export const useOperatorOrganizations = (operatorId: string, page: number) => {
  return useQuery({
    queryKey: ["operators", operatorId, "organizations", page],
    queryFn: () => getOperatorOrganizations(operatorId, page),
  });
};

export const useOrganizationServices = (organizationId: string) => {
  return useQuery({
    queryKey: ["organizations", organizationId, "services"],
    queryFn: () => getOrganizationServices(organizationId),
  });
};

export const useMutationDeleteOrganizationServiceSubscription = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      organizationId,
      serviceId,
      subscriptionId,
    }: {
      organizationId: string;
      serviceId: string;
      subscriptionId: string;
    }) => {
      return deleteOrganizationServiceSubscription(
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
      organizationId,
      serviceId,
    }: {
      organizationId: string;
      serviceId: string;
    }) => {
      return createOrganizationServiceSubscription(organizationId, serviceId);
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
