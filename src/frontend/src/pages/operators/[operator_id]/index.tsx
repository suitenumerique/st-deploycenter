import { useRouter } from "next/router";
import { getGlobalExplorerLayout } from "@/features/layouts/components/GlobalLayout";
import { Container } from "@/features/layouts/components/container/Container";
import { useTranslation } from "react-i18next";
import { DataGrid, usePagination } from "@openfun/cunningham-react";
import { Badge } from "@gouvfr-lasuite/ui-kit";
import Link from "next/link";
import useOperator, { useOperatorOrganizations } from "@/hooks/useQueries";
import { Breadcrumbs } from "@/features/ui/components/breadcrumbs/Breadcrumbs";
import { useEffect } from "react";
import { useBreadcrumbOperator } from "@/features/ui/components/breadcrumbs/Parts";

export default function Operator() {
  const router = useRouter();
  const operatorId = router.query.operator_id as string;
  const { t } = useTranslation();

  const { data: operator, isLoading: isOperatorLoading } =
    useOperator(operatorId);
  const pagination = usePagination({ defaultPage: 1, pageSize: 20 });
  const { data: organizations, isLoading } = useOperatorOrganizations(
    operatorId,
    pagination.page
  );

  useEffect(() => {
    if (organizations) {
      pagination.setPagesCount(
        Math.ceil(organizations.count / pagination.pageSize)
      );
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [organizations]);

  const breadcrumbOperator = useBreadcrumbOperator(
    operatorId,
    operator,
    isOperatorLoading
  );

  return (
    <Container>
      <Breadcrumbs items={[breadcrumbOperator]} />
      <div className="dc__container__content__subtitle">
        {t("organizations.subtitle")}
      </div>
      <DataGrid
        className="dc__organizations__list"
        columns={[
          {
            field: "name",
            headerName: "Name",
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
            field: "population",
            headerName: "Population",
            size: 100,
            renderCell: (params) => {
              return new Intl.NumberFormat().format(params.row.population || 0);
            },
          },
          {
            field: "services",
            headerName: "Services",
            renderCell: (params) => {
              return (
                <div className="dc__organizations__list__item__services">
                  {params.row.service_subscriptions?.map(
                    (serviceSubscription) => (
                      <Badge type="info" key={serviceSubscription.service!.id}>
                        {serviceSubscription.service!.name}
                      </Badge>
                    )
                  )}
                </div>
              );
            },
          },
          {
            field: "rpnpt",
            headerName: "RPNT",
            size: 100,
            renderCell: () => {
              // TODO: Implement RPNT logic.
              return <Badge type="success">wip</Badge>;
            },
          },
        ]}
        rows={organizations?.results || []}
        emptyPlaceholderLabel={t("organizations.empty")}
        pagination={pagination}
        isLoading={isLoading}
      />
    </Container>
  );
}

Operator.getLayout = getGlobalExplorerLayout;
