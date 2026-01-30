import {
  getOperator,
  getOrganizationServices,
  deleteOrganizationServiceSubscription,
  getOperatorOrganizations,
  updateOrganizationServiceSubscription,
  ServiceSubscription,
  updateEntitlement,
  Entitlement,
  getOrganizationAccounts,
  createOrganizationAccount,
  updateAccount,
  updateAccountServiceLink,
  Account,
  getOperatorServices,
  getOperatorMetrics,
  MetricsParams,
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

export const useOperatorServices = (operatorId: string) => {
  return useQuery({
    queryKey: ["operators", operatorId, "services"],
    queryFn: () => getOperatorServices(operatorId),
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

export const useOrganizationServices = (
  operatorId: string,
  organizationId: string
) => {
  return useQuery({
    queryKey: [
      "operators",
      operatorId,
      "organizations",
      organizationId,
      "services",
    ],
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
    }: {
      operatorId: string;
      organizationId: string;
      serviceId: string;
    }) => {
      return deleteOrganizationServiceSubscription(
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

export const useMutationUpdateOrganizationServiceSubscription = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      operatorId,
      organizationId,
      serviceId,
      data,
    }: {
      operatorId: string;
      organizationId: string;
      serviceId: string;
      data: Partial<ServiceSubscription>;
    }) => {
      return updateOrganizationServiceSubscription(
        operatorId,
        organizationId,
        serviceId,
        data
      );
    },
    onSuccess: (data, variables) => {
      queryClient.invalidateQueries({
        queryKey: [
          "operators",
          variables.operatorId,
          "organizations",
          variables.organizationId,
          "services",
        ],
      });
    },
  });
};

export const useMutationUpdateEntitlement = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      entitlementId,
      data,
    }: {
      operatorId: string;
      organizationId: string;
      serviceId: string;
      entitlementId: string;
      data: Partial<Entitlement>;
    }) => {
      return updateEntitlement(entitlementId, data);
    },
    onSuccess: (data, variables) => {
      queryClient.invalidateQueries({
        queryKey: [
          "operators",
          variables.operatorId,
          "organizations",
          variables.organizationId,
          "services",
        ],
      });
    },
  });
};

export const useOrganizationAccounts = (
  operatorId: string,
  organizationId: string,
  params: Parameters<typeof getOrganizationAccounts>[2]
) => {
  return useQuery({
    queryKey: [
      "operators",
      operatorId,
      "organizations",
      organizationId,
      "accounts",
      JSON.stringify(params),
    ],
    queryFn: () => getOrganizationAccounts(operatorId, organizationId, params),
  });
};

export const useMutationCreateAccount = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      operatorId,
      organizationId,
      data,
    }: {
      operatorId: string;
      organizationId: string;
      data: Parameters<typeof createOrganizationAccount>[2];
    }) => {
      return createOrganizationAccount(operatorId, organizationId, data);
    },
    onSuccess: (data, variables) => {
      queryClient.invalidateQueries({
        queryKey: [
          "operators",
          variables.operatorId,
          "organizations",
          variables.organizationId,
          "accounts",
        ],
      });
    },
  });
};

export const useMutationUpdateAccount = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      accountId,
      data,
    }: {
      operatorId: string;
      organizationId: string;
      accountId: string;
      data: Partial<Pick<Account, "roles">>;
    }) => {
      return updateAccount(accountId, data);
    },
    onSuccess: (data, variables) => {
      queryClient.invalidateQueries({
        queryKey: [
          "operators",
          variables.operatorId,
          "organizations",
          variables.organizationId,
          "accounts",
        ],
      });
    },
  });
};

export const useMutationUpdateAccountServiceLink = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      accountId,
      serviceId,
      data,
    }: {
      operatorId: string;
      organizationId: string;
      accountId: string;
      serviceId: string;
      data: { roles: string[] };
    }) => {
      return updateAccountServiceLink(accountId, serviceId, data);
    },
    onSuccess: (data, variables) => {
      queryClient.invalidateQueries({
        queryKey: [
          "operators",
          variables.operatorId,
          "organizations",
          variables.organizationId,
          "accounts",
        ],
      });
    },
  });
};

export const useOperatorMetrics = (
  operatorId: string,
  params: MetricsParams | null
) => {
  return useQuery({
    queryKey: ["operators", operatorId, "metrics", JSON.stringify(params)],
    queryFn: () => getOperatorMetrics(operatorId, params!),
    enabled: !!operatorId && !!params?.key && !!params?.service,
  });
};

export default useOperator;
