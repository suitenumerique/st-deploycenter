import {
  getOperator,
  getOrganizationServices,
  deleteOrganizationServiceSubscription,
  createOrganizationServiceSubscription,
} from "@/features/api/Repository";
import { getOrganization } from "@/features/api/Repository";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

export const useOperator = (operatorId: string) => {
  return useQuery({
    queryKey: ["operators", operatorId],
    refetchOnWindowFocus: false,
    refetchOnMount: false,
    queryFn: () => getOperator(operatorId),
    enabled: !!operatorId,
  });
};

export const useOrganization = (organizationId: string) => {
  return useQuery({
    queryKey: ["organizations", organizationId],
    refetchOnWindowFocus: false,
    refetchOnMount: false,
    queryFn: () => getOrganization(organizationId),
  });
};

export const useOrganizationServices = (organizationId: string) => {
  return useQuery({
    queryKey: ["organizations", organizationId, "services"],
    refetchOnWindowFocus: false,
    refetchOnMount: false,
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
    },
  });
};

export default useOperator;
