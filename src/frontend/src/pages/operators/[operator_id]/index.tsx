import { useRouter } from "next/router";
import { useQuery } from "@tanstack/react-query";
import {
  getOperator,
  getOperatorOrganizations,
} from "@/features/api/Repository";
import { getGlobalExplorerLayout } from "@/features/layouts/components/GlobalLayout";
import { Container } from "@/features/layouts/components/container/Container";
import { useTranslation } from "react-i18next";
import { Button, DataGrid, usePagination } from "@openfun/cunningham-react";
import { Badge } from "@gouvfr-lasuite/ui-kit";
import Link from "next/link";
import useOperator, { useOperatorOrganizations } from "@/hooks/useQueries";
import { Breadcrumbs } from "@/features/ui/components/breadcrumbs/Breadcrumbs";
import { useEffect } from "react";

const FAKE_SERVICES = [
  "Fichiers",
  "Docs",
  "FI ANCT",
  "Messages",
  "Espace sur Demande",
  "FI Adico",
];

export default function Operator() {
  const router = useRouter();
  const operatorId = router.query.operator_id as string;
  const { t } = useTranslation();

  const { data: operator } = useOperator(operatorId);
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

  return (
    <Container>
      <Breadcrumbs
        items={[
          {
            content: (
              <button
                className="c__breadcrumbs__button"
                data-testid="breadcrumb-button"
                onClick={() => router.push(`/operators/${operatorId}`)}
              >
                {t("organizations.title", { operator: operator?.name })}
              </button>
            ),
          },
        ]}
      />
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
          },
          {
            field: "services",
            headerName: "Services",
            renderCell: (params) => {
              // TODO: Implement services logic.
              const getRandomServices = () => {
                const shuffled = [...FAKE_SERVICES].sort(
                  () => 0.5 - Math.random()
                );
                const count = Math.floor(Math.random() * 3) + 1; // Random number between 1 and 3
                return shuffled.slice(0, count);
              };

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
              return (
                <Badge type="success">{t("organizations.rpnt.yes")}</Badge>
              );
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
