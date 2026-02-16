import { useRouter } from "next/router";
import {
  getGlobalExplorerLayout,
  useOperatorContext,
} from "@/features/layouts/components/GlobalLayout";
import { Container } from "@/features/layouts/components/container/Container";
import { useTranslation } from "react-i18next";
import {
  DataGrid,
  Input,
  Select,
  SortModel,
  Tooltip,
  usePagination,
} from "@openfun/cunningham-react";
import { Badge, Icon } from "@gouvfr-lasuite/ui-kit";
import { RpntBadge } from "@/features/ui/components/organization/RpntBadge";
import Link from "next/link";
import { useOperatorOrganizations, useOperatorServices } from "@/hooks/useQueries";
import { Breadcrumbs } from "@/features/ui/components/breadcrumbs/Breadcrumbs";
import { useEffect, useRef, useState } from "react";
import { useBreadcrumbOperator } from "@/features/ui/components/breadcrumbs/Parts";
import { sortModelToOrdering } from "@/features/api/Repository";

export default function Operator() {
  const router = useRouter();
  const operatorId = router.query.operator_id as string;
  const { t } = useTranslation();

  const {
    operator,
    operatorQuery: { isLoading: isOperatorLoading },
  } = useOperatorContext();

  const [sortModel, setSortModel] = useState<SortModel>([]);
  const [search, setSearch] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [serviceFilter, setServiceFilter] = useState("");
  const pagination = usePagination({
    defaultPage: 1,
    pageSize: 20,
  });

  const { data: operatorServices } = useOperatorServices(operatorId);

  const { data: organizations, isLoading } = useOperatorOrganizations(
    operatorId,
    {
      page: pagination.page,
      search,
      ordering: sortModelToOrdering(sortModel),
      type: typeFilter || undefined,
      service: serviceFilter || undefined,
    }
  );

  // Update pages count when organizations are fetched.
  useEffect(() => {
    if (organizations) {
      pagination.setPagesCount(
        Math.ceil(organizations.count / pagination.pageSize)
      );
    }
  }, [organizations]);

  const breadcrumbOperator = useBreadcrumbOperator(
    operatorId,
    operator,
    isOperatorLoading
  );

  const searchTimeout = useRef<NodeJS.Timeout | null>(null);

  // Clear timeout when component unmounts.
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
      // Reset pagination to page 1 when search changes
      if (pagination.page !== 1) {
        pagination.setPage(1);
      }
    }, 300);
  };

  return (
    <Container
      titleNode={
        <>
          <Breadcrumbs items={[breadcrumbOperator]} />
          <div className="dc__container__content__subtitle">
            {t("organizations.subtitle")}
          </div>
        </>
      }
    >
      <div className="dc__organizations__search">
        <Input
          icon={<Icon name="search" />}
          label={t("organizations.search")}
          fullWidth
          onChange={onSearchChange}
        />
        <div className="dc__organizations__search__filters">
          <Select
            label={t("organizations.filter.type")}
            value={typeFilter}
            onChange={(e) => {
              setTypeFilter((e.target.value as string) || "");
              // Reset pagination to page 1 when filter changes
              if (pagination.page !== 1) {
                pagination.setPage(1);
              }
            }}
            options={[
              { label: t("organizations.filter.types.all_types"), value: "" },
              { label: t("organizations.filter.types.commune"), value: "commune" },
              { label: t("organizations.filter.types.epci"), value: "epci" },
              { label: t("organizations.filter.types.departement"), value: "departement" },
              { label: t("organizations.filter.types.region"), value: "region" },
              { label: t("organizations.filter.types.other"), value: "other" },
            ]}
          />
          <Select
            label={t("organizations.filter.service")}
            value={serviceFilter}
            onChange={(e) => {
              setServiceFilter((e.target.value as string) || "");
              if (pagination.page !== 1) {
                pagination.setPage(1);
              }
            }}
            options={[
              { label: t("organizations.filter.services.all"), value: "" },
              ...(operatorServices?.results || []).map((service) => ({
                label: service.name,
                value: service.id,
              })),
            ]}
          />
        </div>
      </div>
      <DataGrid
        className="dc__organizations__list"
        columns={[
          {
            field: "name",
            headerName: "Organisation",
            highlight: true,
            renderCell: (params) => {
              return (
                <Link
                  href={`/operators/${operatorId}/organizations/${params.row.id}`}
                >
                  {params.row.name}
                </Link>
              );
            },
          },
          {
            field: "type",
            headerName: t("organizations.type"),
            renderCell: (params) => {
              const typeLabel =
                params.row.type === "commune"
                  ? t("organizations.filter.types.commune")
                  : params.row.type === "epci"
                    ? t("organizations.filter.types.epci")
                    : params.row.type === "departement"
                      ? t("organizations.filter.types.departement")
                      : params.row.type === "region"
                        ? t("organizations.filter.types.region")
                        : t("organizations.filter.types.other");
              return <>{typeLabel}</>;
            },
          },
          {
            field: "epci_libelle",
            headerName: "Territoire",
            renderCell: (params) => {
              return (
                <>
                  {params.row.type === "commune" ? (<>
                  {params.row.departement_code_insee}・{params.row.epci_libelle}
                  </>
                  ) : (params.row.type === "region" ? "" : (
                    <>
                    {params.row.departement_code_insee}
                    </>
                  ))}
                </>
              );
            },
          },
          {
            field: "services",
            headerName: "Services",
            size: 50,
            enableSorting: false,
            renderCell: (params) => {
              return (
                <div className="dc__organizations__list__item__services">
                  <Tooltip
                    content={
                      <Link
                        href={`/operators/${operatorId}/organizations/${params.row.id}`}
                      >
                        {params.row.service_subscriptions
                          .filter((s) => s.is_active)
                          .map(
                            (serviceSubscription) =>
                              serviceSubscription.service!.name
                          )
                          .join(", ")}
                      </Link>
                    }
                  >
                    <Link
                      href={`/operators/${operatorId}/organizations/${params.row.id}`}
                    >
                      <Badge
                        type={
                          params.row.service_subscriptions.filter((s) => s.is_active).length > 0
                            ? "info"
                            : "neutral"
                        }
                      >
                        {params.row.service_subscriptions.filter((s) => s.is_active).length}
                      </Badge>
                    </Link>
                  </Tooltip>
                </div>
              );
            },
          },
          {
            field: "rpnpt",
            headerName: "RPNT",
            size: 100,
            enableSorting: false,
            renderCell: (params) => (
              <RpntBadge rpnt={params.row.rpnt} siret={params.row.siret} />
            ),
          },
        ]}
        rows={organizations?.results || []}
        emptyPlaceholderLabel={t("organizations.empty")}
        pagination={pagination}
        isLoading={isLoading}
        sortModel={sortModel}
        onSortModelChange={setSortModel}
      />
    </Container>
  );
}

Operator.getLayout = getGlobalExplorerLayout;
