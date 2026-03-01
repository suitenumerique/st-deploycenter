import {
  DataGrid,
  Input,
  Select,
  SortModel,
  Button,
  usePagination,
  useModals,
} from "@openfun/cunningham-react";
import { Icon } from "@gouvfr-lasuite/ui-kit";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useRouter } from "next/router";
import {
  useOrganizationAccounts,
  useOrganizationServices,
  useMutationDeleteAccount,
} from "@/hooks/useQueries";
import { sortModelToOrdering, Account } from "@/features/api/Repository";
import { GLOBAL_ROLES, getServiceRoles } from "@/features/accounts/roles";
import { AccountModal } from "./AccountModal";

interface AccountsTabProps {
  operatorId: string;
  organizationId: string;
}

export const AccountsTab = ({
  operatorId,
  organizationId,
}: AccountsTabProps) => {
  const { t } = useTranslation();
  const router = useRouter();
  const modals = useModals();
  const deleteAccount = useMutationDeleteAccount();

  const roleFilter = (router.query.role as string) || "";
  const typeFilter = (router.query.type as string) || "";

  const setUrlFilter = (key: string, value: string) => {
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    const { [key]: _, ...restQuery } = router.query;
    const query: Record<string, string | string[] | undefined> = { ...restQuery };
    if (value) {
      query[key] = value;
    }
    router.push(
      { pathname: router.pathname, query },
      undefined,
      { shallow: true }
    );
  };

  const setRoleFilter = (role: string) => setUrlFilter("role", role);
  const setTypeFilter = (type: string) => setUrlFilter("type", type);

  const [sortModel, setSortModel] = useState<SortModel>([]);
  const [search, setSearch] = useState("");
  const [isAddModalOpen, setIsAddModalOpen] = useState(false);
  const [editingAccount, setEditingAccount] = useState<Account | null>(null);

  const pagination = usePagination({
    defaultPage: 1,
    pageSize: 20,
  });

  const { data: services } = useOrganizationServices(
    operatorId,
    organizationId
  );

  const { data: accounts, isLoading } = useOrganizationAccounts(
    operatorId,
    organizationId,
    {
      page: pagination.page,
      search: search || undefined,
      ordering: sortModelToOrdering(sortModel) || undefined,
      type: typeFilter || undefined,
      role: roleFilter || undefined,
    }
  );

  const configuredServices = services?.results?.filter(
    (s) => s.operator_config
  );

  const roleFilterOptions = [
    { label: t("accounts.filter.roles.all"), value: "" },
    ...GLOBAL_ROLES.map((r) => ({
      label: `${t("accounts.roles.global_title")} : ${t(r.labelKey)}`,
      value: `org.${r.value}`,
    })),
    ...(configuredServices || []).flatMap((service) =>
      getServiceRoles(service.type).map((r) => ({
        label: `${service.name} : ${t(r.labelKey)}`,
        value: `service.${service.id}.${r.value}`,
      }))
    ),
  ];

  useEffect(() => {
    if (accounts) {
      pagination.setPagesCount(
        Math.ceil(accounts.count / pagination.pageSize)
      );
    }
  }, [accounts]);

  const searchTimeout = useRef<NodeJS.Timeout | null>(null);

  useEffect(() => {
    return () => {
      if (searchTimeout.current) {
        clearTimeout(searchTimeout.current);
      }
    };
  }, []);

  const onSearchChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const value = e.target.value;
    if (searchTimeout.current) {
      clearTimeout(searchTimeout.current);
    }
    searchTimeout.current = setTimeout(() => {
      setSearch(value);
      if (pagination.page !== 1) {
        pagination.setPage(1);
      }
    }, 300);
  };

  return (
    <div className="dc__accounts">
      <div className="dc__accounts__toolbar">
        <Input
          icon={<Icon name="search" />}
          label={t("accounts.search")}
          fullWidth
          onChange={onSearchChange}
        />
        <Select
          label={t("accounts.filter.type")}
          value={typeFilter}
          onChange={(e) => {
            setTypeFilter((e.target.value as string) || "");
            if (pagination.page !== 1) {
              pagination.setPage(1);
            }
          }}
          options={[
            { label: t("accounts.filter.types.all"), value: "" },
            { label: t("accounts.filter.types.user"), value: "user" },
            { label: t("accounts.filter.types.mailbox"), value: "mailbox" },
          ]}
        />
        <Select
          label={t("accounts.filter.role")}
          value={roleFilter}
          onChange={(e) => {
            setRoleFilter((e.target.value as string) || "");
            if (pagination.page !== 1) {
              pagination.setPage(1);
            }
          }}
          options={roleFilterOptions}
        />
        <Button
          className="dc__accounts__toolbar__add"
          onClick={() => setIsAddModalOpen(true)}
          icon={<Icon name="add" />}
        >
          {t("accounts.add")}
        </Button>
      </div>
      <DataGrid
        className="dc__accounts__list"
        columns={[
          {
            field: "email",
            headerName: t("accounts.columns.email"),
            highlight: true,
            renderCell: (params) => (
              <span className="dc__accounts__ellipsis">
                {params.row.email}
              </span>
            ),
          },
          {
            field: "external_id",
            headerName: t("accounts.columns.external_id"),
            renderCell: (params) => (
              <span className="dc__accounts__ellipsis">
                {params.row.external_id}
              </span>
            ),
          },
          {
            field: "type",
            headerName: t("accounts.columns.type"),
            size: 120,
            renderCell: (params) => (
              <>
                {t(
                  `accounts.filter.types.${params.row.type}`,
                  params.row.type
                )}
              </>
            ),
          },
          {
            field: "roles",
            headerName: t("accounts.columns.roles"),
            enableSorting: false,
            renderCell: (params) => {
              const account = params.row as Account;
              const parts: string[] = [];

              account.roles?.forEach((role) => {
                const def = GLOBAL_ROLES.find((r) => r.value === role);
                const label = def ? t(def.labelKey) : role;
                parts.push(`${t("accounts.roles.global_title")} : ${label}`);
              });

              account.service_links?.forEach((link) => {
                const serviceDefs = getServiceRoles(link.service.type);
                Object.entries(link.roles || {}).forEach(([role, config]) => {
                  const def = serviceDefs.find((r) => r.value === role);
                  const label = def ? t(def.labelKey) : role;
                  const scopeDomains = ((config.scope?.domains ?? []) as string[]);
                  if (scopeDomains.length > 0) {
                    parts.push(`${link.service.name} : ${label} (${scopeDomains.join(", ")})`);
                  } else {
                    parts.push(`${link.service.name} : ${label}`);
                  }
                });
              });

              if (parts.length === 0) return <>-</>;
              return (
                <div className="dc__accounts__roles-cell">
                  {parts.map((part, i) => (
                    <span key={i}>{part}</span>
                  ))}
                </div>
              );
            },
          },
          {
            field: "actions",
            headerName: "",
            size: 120,
            enableSorting: false,
            renderCell: (params) => (
              <div style={{ display: "flex", gap: "0.5rem" }}>
                <Button
                  size="small"
                  color="secondary"
                  icon={<Icon name="edit" />}
                  onClick={() => setEditingAccount(params.row as Account)}
                />
                <Button
                  size="small"
                  color="secondary"
                  icon={<Icon name="delete" />}
                  onClick={async () => {
                    const decision = await modals.confirmationModal({
                      children: t("accounts.delete_confirmation"),
                    });
                    if (decision === "yes") {
                      deleteAccount.mutate({
                        operatorId,
                        organizationId,
                        accountId: (params.row as Account).id,
                      });
                    }
                  }}
                />
              </div>
            ),
          },
        ]}
        rows={accounts?.results || []}
        emptyPlaceholderLabel={t("accounts.empty")}
        pagination={pagination}
        isLoading={isLoading}
        sortModel={sortModel}
        onSortModelChange={setSortModel}
      />
      <AccountModal
        operatorId={operatorId}
        organizationId={organizationId}
        account={editingAccount}
        isOpen={isAddModalOpen || !!editingAccount}
        onClose={() => {
          setIsAddModalOpen(false);
          setEditingAccount(null);
        }}
      />
    </div>
  );
};
