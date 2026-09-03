import {
  getOperator,
  getOrganizationServices,
  getOperatorOrganizations,
  updateOrganizationServiceSubscription,
  ServiceSubscriptionInput,
  getOrganizationAccounts,
  createOrganizationAccount,
  updateAccount,
  deleteAccount,
  updateAccountServiceLink,
  Account,
  getOperatorServices,
  updateOperatorOrganizationRole,
  updateOrganizationProconnectDomains,
  checkDomains,
  DomainCheck,
} from "@/features/api/Repository";
import { getOrganization } from "@/features/api/Repository";
import { useEffect, useState } from "react";
import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

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

export const useMutationUpdateOrganizationProconnectDomains = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      operatorId,
      organizationId,
      payload,
    }: {
      operatorId: string;
      organizationId: string;
      payload: { manual?: string[]; requested?: string[]; discarded?: string[] };
    }) =>
      updateOrganizationProconnectDomains(operatorId, organizationId, payload),
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

/**
 * DNS delegation and RPNT 1.2 checks for a list of domains.
 *
 * Each domain is checked once and its verdict kept, so adding one only resolves
 * that one — a check walks the DNS from the root and caches no answer, so
 * re-checking a list of ten to add an eleventh would cost eleven walks and could
 * run into the batch deadline. Answers are held for as long as the modal is open;
 * closing and reopening it checks everything again, which is how a user re-checks
 * a delegation they just fixed.
 *
 * A domain the backend drops from the results (not well-formed) still counts as
 * answered, or it would be asked for again on every render.
 *
 * A failed batch is reported through `checksFailed` rather than retried: the query
 * key is the list of unanswered domains, so it does not change while the batch is
 * unanswered and an automatic retry would just loop. `retryChecks` is the way back,
 * driven by the user.
 */
export const useDomainsChecks = (
  operatorId: string,
  organizationId: string,
  domains: string[],
  enabled = true
) => {
  // domain -> its verdict, or null when the backend answered without one.
  const [answers, setAnswers] = useState<Record<string, DomainCheck | null>>({});
  // The parts of the response that describe the service, not a domain.
  const [rules, setRules] = useState<{
    expectedNameservers: string[];
    modesWithTarget: string[];
  } | null>(null);

  const missing = domains.filter((domain) => !(domain in answers)).sort();
  const { data, isFetching, isError, refetch } = useQuery({
    queryKey: [
      "operators",
      operatorId,
      "organizations",
      organizationId,
      "domains-check",
      missing.join(","),
    ],
    queryFn: () => checkDomains(operatorId, organizationId, missing),
    // The empty list is worth one call: it carries no lookup, but it carries the
    // nameservers and the mode rules the modal needs before any domain exists.
    enabled:
      enabled &&
      !!operatorId &&
      !!organizationId &&
      (missing.length > 0 || rules === null),
    staleTime: 5 * 60 * 1000,
    retry: false,
  });

  const requested = missing.join(",");
  useEffect(() => {
    if (!data) {
      return;
    }
    setRules({
      expectedNameservers: data.expected_nameservers,
      modesWithTarget: data.modes_with_target,
    });
    setAnswers((previous) => {
      const next = { ...previous };
      for (const domain of requested ? requested.split(",") : []) {
        next[domain] = null;
      }
      for (const result of data.results) {
        next[result.domain] = result;
      }
      return next;
    });
    // `requested` is the query key: it changes with `data`, and reading it here
    // keeps the merge tied to the batch that produced it.
  }, [data, requested]);

  return {
    checkOf: (domain: string) => answers[domain] ?? undefined,
    expectedNameservers: rules?.expectedNameservers ?? [],
    modesWithTarget: rules?.modesWithTarget ?? [],
    // Only a domain of the batch in flight is still waiting for its verdict.
    isCheckPending: (domain: string) => isFetching && !(domain in answers),
    // The last batch failed and its domains have no verdict; without this the
    // modal would show them blank with no way to ask again.
    checksFailed: isError && !isFetching,
    retryChecks: () => void refetch(),
  };
};

export default useOperator;
