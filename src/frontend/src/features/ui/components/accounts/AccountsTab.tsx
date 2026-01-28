import {
  DataGrid,
  Input,
  Select,
  SortModel,
  Button,
  usePagination,
} from "@openfun/cunningham-react";
import { Icon } from "@gouvfr-lasuite/ui-kit";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useOrganizationAccounts } from "@/hooks/useQueries";
import { sortModelToOrdering } from "@/features/api/Repository";
import { Account } from "@/features/api/Repository";
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

  const [sortModel, setSortModel] = useState<SortModel>([]);
  const [search, setSearch] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [roleFilter, setRoleFilter] = useState("");
  const [isAddModalOpen, setIsAddModalOpen] = useState(false);
  const [editingAccount, setEditingAccount] = useState<Account | null>(null);

  const pagination = usePagination({
    defaultPage: 1,
    pageSize: 20,
  });

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
    if (searchTimeout.current) {
      clearTimeout(searchTimeout.current);
    }
    searchTimeout.current = setTimeout(() => {
      setSearch(e.target.value);
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
          options={[
            { label: t("accounts.filter.roles.all"), value: "" },
            { label: "admin", value: "admin" },
            { label: "member", value: "member" },
          ]}
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
          },
          {
            field: "external_id",
            headerName: t("accounts.columns.external_id"),
          },
          {
            field: "type",
            headerName: t("accounts.columns.type"),
          },
          {
            field: "roles",
            headerName: t("accounts.columns.roles"),
            enableSorting: false,
            renderCell: (params) => (
              <>{params.row.roles?.join(", ") || "-"}</>
            ),
          },
          {
            field: "service_links",
            headerName: t("accounts.columns.services"),
            enableSorting: false,
            renderCell: (params) => (
              <>{params.row.service_links?.length || 0}</>
            ),
          },
          {
            field: "actions",
            headerName: "",
            size: 80,
            enableSorting: false,
            renderCell: (params) => (
              <Button
                size="small"
                color="secondary"
                icon={<Icon name="edit" />}
                onClick={() => setEditingAccount(params.row as Account)}
              />
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
