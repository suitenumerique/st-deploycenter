import { Container } from "@/features/layouts/components/container/Container";
import {
  getGlobalExplorerLayout,
  useOperatorContext,
} from "@/features/layouts/components/GlobalLayout";
import { useRouter } from "next/router";
import { useOrganization, useOrganizationServices } from "@/hooks/useQueries";
import { useTranslation } from "react-i18next";
import { SERVICE_TYPE_PROCONNECT } from "@/features/api/Repository";
import { Breadcrumbs } from "@/features/ui/components/breadcrumbs/Breadcrumbs";
import { useMemo } from "react";
import { useBreadcrumbOperator } from "@/features/ui/components/breadcrumbs/Parts";
import { Spinner } from "@gouvfr-lasuite/ui-kit";
import { ServiceBlockDispatcher } from "@/features/ui/components/service/ServiceBlockDispatcher";

export default function Organization() {
  const router = useRouter();
  const operatorId = router.query.operator_id as string;
  const organizationId = router.query.id as string;
  const { t } = useTranslation();
  const {
    operator,
    operatorQuery: { isLoading: isOperatorLoading },
  } = useOperatorContext();
  const { data: organization, isLoading: isOrganizationLoading } =
    useOrganization(operatorId, organizationId);
  const { data: services, isLoading: isServicesLoading } =
    useOrganizationServices(operatorId, organizationId);
  const breadcrumbOperator = useBreadcrumbOperator(
    operatorId,
    operator,
    isOperatorLoading
  );

  // Set ProConnect service at the beginning of the list, then sort by display priority.
  const servicesOrdered = useMemo(() => {
    if (!services?.results) {
      return [];
    }
    return [...services.results].sort((a, b) => {
      const aIsProConnect = a.type === SERVICE_TYPE_PROCONNECT;
      const bIsProConnect = b.type === SERVICE_TYPE_PROCONNECT;
      if (aIsProConnect && !bIsProConnect) return -1;
      if (!aIsProConnect && bIsProConnect) return 1;
      const priorityA = a.operator_config?.display_priority ?? -Infinity;
      const priorityB = b.operator_config?.display_priority ?? -Infinity;
      return priorityB - priorityA; // descending order, nulls at the end
    });
  }, [services]);

  return (
    <Container
      titleNode={
        <>
          <Breadcrumbs
            items={[
              breadcrumbOperator,
              {
                content: (
                  <button
                    className="c__breadcrumbs__button"
                    data-testid="breadcrumb-button"
                    onClick={() =>
                      router.push(
                        `/operators/${operatorId}/organizations/${organizationId}`
                      )
                    }
                  >
                    {organization?.name}
                    {isOrganizationLoading && <Spinner />}
                  </button>
                ),
              },
            ]}
          />
          <div className="dc__container__content__subtitle">
            {t("organizations.services.subtitle")}
          </div>
        </>
      }
    >
      <div className="dc__organization__header">
        <div>
          <div className="dc__organization__header__top">
            <span className="dc__organization__header__top__name">
              {organization?.name}
              <span className="dc__organization__header__top__code_postal">
                ・{organization?.code_postal}
              </span>
            </span>
          </div>
          <div className="dc__organization__header__details">
            <div className="dc__organization__header__details__item">
              <span className="dc__organization__header__details__item__label">
                {t("organizations.details.population")}
              </span>
              <span className="dc__organization__header__details__item__value">
                {organization?.population}
              </span>
            </div>
          </div>
        </div>
        <div>
          <div className="dc__organization__header__image"></div>
        </div>
      </div>
      <div className="dc__services__list">
        {isServicesLoading || !organization || !operator ? (
          <Spinner />
        ) : (
          servicesOrdered?.map((service) => (
            <ServiceBlockDispatcher
              key={service.id}
              service={service}
              organization={organization}
            />
          ))
        )}
      </div>
    </Container>
  );
}

Organization.getLayout = getGlobalExplorerLayout;
