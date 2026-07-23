import {
  getOperator,
  getOrganizationServices,
  deleteOrganizationServiceSubscription,
  getOperatorOrganizations,
  updateOrganizationServiceSubscription,
  ServiceSubscriptionInput,
  updateEntitlement,
  Entitlement,
  getOrganizationAccounts,
  createOrganizationAccount,
  updateAccount,
  deleteAccount,
  updateAccountServiceLink,
  Account,
  getOperatorServices,
  updateOperatorOrganizationRole,
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
  params: Parameters<typeof getOperatorOrganizations>[1],
  enabled = true
) => {
  return useQuery({
    queryKey: [
      "operators",
      operatorId,
      "organizations",
      JSON.stringify(params),
    ],
    queryFn: () => getOperatorOrganizations(operatorId, params),
    enabled: enabled && !!operatorId,
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
      data: ServiceSubscriptionInput;
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

export const useMutationDeleteAccount = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      accountId,
    }: {
      operatorId: string;
      organizationId: string;
      accountId: string;
    }) => {
      return deleteAccount(accountId);
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
      data: { roles: Record<string, { scope?: Record<string, unknown> }> };
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

export const useServiceAdminCount = (
  operatorId: string,
  organizationId: string,
  serviceId: string,
  includeServiceCount: boolean = true
) => {
  return useQuery({
    // Nested under the "accounts" namespace so existing account mutations
    // (which invalidate [..., "accounts"]) also refresh these counts.
    queryKey: [
      "operators",
      operatorId,
      "organizations",
      organizationId,
      "accounts",
      serviceId,
      "serviceAdminCount",
      includeServiceCount,
    ],
    queryFn: async () => {
      // Only fetch the per-service count when it will actually be displayed.
      const [globalAdmins, serviceAdmins] = await Promise.all([
        getOrganizationAccounts(operatorId, organizationId, {
          role: "org.admin",
        }),
        includeServiceCount
          ? getOrganizationAccounts(operatorId, organizationId, {
              role: `service.${serviceId}.admin`,
            })
          : Promise.resolve(null),
      ]);

      // Use count field for total count (handles pagination)
      return {
        globalCount: globalAdmins.count,
        serviceCount: serviceAdmins?.count ?? 0,
      };
    },
    enabled: !!operatorId && !!organizationId && !!serviceId,
  });
};

export const useMutationUpdateOperatorOrganizationRole = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      operatorId,
      organizationId,
      data,
    }: {
      operatorId: string;
      organizationId: string;
      data: { operator_admins_have_admin_role: boolean };
    }) => updateOperatorOrganizationRole(operatorId, organizationId, data),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({
        queryKey: [
          "operators",
          variables.operatorId,
          "organizations",
          variables.organizationId,
        ],
      });
    },
  });
};

export default useOperator;
