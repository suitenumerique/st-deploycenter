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
  SortModel,
  Tooltip,
  usePagination,
} from "@openfun/cunningham-react";
import { Badge, Icon, IconSize } from "@gouvfr-lasuite/ui-kit";
import Link from "next/link";
import { useOperatorOrganizations } from "@/hooks/useQueries";
import { Breadcrumbs } from "@/features/ui/components/breadcrumbs/Breadcrumbs";
import { useEffect, useMemo, useRef, useState } from "react";
import { useBreadcrumbOperator } from "@/features/ui/components/breadcrumbs/Parts";
import {
  sortModelToOrdering,
  orderingToSortModel,
} from "@/features/api/Repository";

export default function Operator() {
  const router = useRouter();
  const operatorId = router.query.operator_id as string;
  const { t } = useTranslation();

  const {
    operator,
    operatorQuery: { isLoading: isOperatorLoading },
  } = useOperatorContext();

  // Read page from URL query parameters, default to 1 if invalid
  const queryParamsPage = useMemo(() => {
    const pageParam = router.query.page;
    if (typeof pageParam === "string") {
      const page = parseInt(pageParam, 10);
      return isNaN(page) || page < 1 ? 1 : page;
    }
    return 1;
  }, [router.query.page]);

  // Read search from URL query parameters, default to empty string
  const queryParamsSearch = useMemo(() => {
    const searchParam = router.query.search;
    return typeof searchParam === "string" ? searchParam : "";
  }, [router.query.search]);

  // Read sort ordering from URL query parameters, default to empty array
  const queryParamsSortModel = useMemo(() => {
    const orderingParam = router.query.ordering;
    if (typeof orderingParam === "string" && orderingParam.trim() !== "") {
      return orderingToSortModel(orderingParam);
    }
    return [];
  }, [router.query.ordering]);

  const [sortModel, setSortModel] = useState<SortModel>(queryParamsSortModel);

  const [search, setSearch] = useState(queryParamsSearch);
  const pagination = usePagination({
    defaultPage: queryParamsPage,
    pageSize: 20,
  });

  const { data: organizations, isLoading } = useOperatorOrganizations(
    operatorId,
    {
      page: pagination.page,
      search,
      ordering: sortModelToOrdering(sortModel),
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

  // Update URL when filters changes.
  useEffect(() => {
    const newQuery = { ...router.query };
    let updated = false;
    if (search !== queryParamsSearch) {
      if (search === "") {
        // Remove search parameter if it's empty
        delete newQuery.search;
      } else {
        newQuery.search = search;
      }
      updated = true;
    }

    if (pagination.page !== queryParamsPage) {
      if (pagination.page === 1) {
        // Remove page parameter if it's page 1
        delete newQuery.page;
      } else {
        newQuery.page = pagination.page.toString();
      }
      updated = true;
    }

    const currentOrdering = sortModelToOrdering(queryParamsSortModel);
    const newOrdering = sortModelToOrdering(sortModel);
    if (newOrdering !== currentOrdering) {
      if (newOrdering === "") {
        // Remove ordering parameter if it's empty
        delete newQuery.ordering;
      } else {
        newQuery.ordering = newOrdering;
      }
      updated = true;
    }

    if (updated) {
      router.replace(
        {
          pathname: router.pathname,
          query: newQuery,
        },
        undefined,
        { shallow: true }
      );
    }
  }, [
    search,
    queryParamsSearch,
    pagination.page,
    queryParamsPage,
    sortModel,
    queryParamsSortModel,
    router,
  ]);

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
    if (searchTimeout.current) {
      clearTimeout(searchTimeout.current);
    }
    searchTimeout.current = setTimeout(() => {
      setSearch(e.target.value);
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
          value={search}
          onChange={onSearchChange}
        />
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
            field: "epci_libelle",
            headerName: "Territoire",
            renderCell: (params) => {
              return (
                <>
                  {params.row.departement_code_insee}・{params.row.epci_libelle}
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
                          params.row.service_subscriptions.length > 0
                            ? "info"
                            : "neutral"
                        }
                      >
                        {params.row.service_subscriptions.length}
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
            renderCell: (params) => {
              if ((params.row.rpnt || []).includes("a")) {
                return (
                  <Badge type="success">
                    <Icon name="check" size={IconSize.SMALL} />
                  </Badge>
                );
              } else if ((params.row.rpnt || []).includes("1.a") || (params.row.rpnt || []).includes("2.a")) {
                return (
                  <Badge type="warning">
                    <Icon name="warning" size={IconSize.SMALL} />
                  </Badge>
                );
              } else {
                return (
                  <Badge type="danger">
                    <Icon name="close" size={IconSize.SMALL} />
                  </Badge>
                );
              }
            },
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
