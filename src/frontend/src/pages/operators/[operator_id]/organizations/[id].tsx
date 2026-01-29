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
import { useMemo, useState } from "react";
import { useBreadcrumbOperator } from "@/features/ui/components/breadcrumbs/Parts";
import { Spinner } from "@gouvfr-lasuite/ui-kit";
import { RpntBadge } from "@/features/ui/components/organization/RpntBadge";
import { ServiceBlockDispatcher } from "@/features/ui/components/service/ServiceBlockDispatcher";
import { AccountsTab } from "@/features/ui/components/accounts/AccountsTab";

type Tab = "services" | "accounts";

export default function Organization() {
  const router = useRouter();
  const operatorId = router.query.operator_id as string;
  const organizationId = router.query.id as string;
  const { t } = useTranslation();
  const [activeTab, setActiveTab] = useState<Tab>("services");
  const {
    operator,
    operatorQuery: { isLoading: isOperatorLoading },
  } = useOperatorContext();
  const { data: organization, isLoading: isOrganizationLoading } =
    useOrganization(operatorId, organizationId);
  const {
    data: services,
    isLoading: isServicesLoading,
    isFetching: isServicesFetching,
  } = useOrganizationServices(operatorId, organizationId);
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
            {activeTab === "services"
              ? t("organizations.services.subtitle")
              : t("accounts.search")}
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
                <>
                {organization?.type === "commune" ? (
                  <>
                  ・{organization?.code_postal}
                  </>
                ) : (
                  organization?.type === "region" ? (
                    <>
                      ・{t("organizations.filter.types.region")}
                    </>
                  ) : (
                    organization?.type === "departement" ? (
                      <>
                      ・{t("organizations.filter.types.departement")}
                      </>
                    ) : (
                      organization?.type === "epci" ? (
                        <>
                        ・{t("organizations.filter.types.epci")}
                        </>
                      ) : ""
                    
                  )))}
                </>
              </span>
            </span>
          </div>
          <div className="dc__organization__header__details">
            {organization?.population && (
              <div className="dc__organization__header__details__item">
                <span className="dc__organization__header__details__item__label">
                  {t("organizations.details.population")}
                </span>
                <span className="dc__organization__header__details__item__value">
                  {organization?.population}
                </span>
              </div>
            )}
            {organization?.siret && (
              <div className="dc__organization__header__details__item">
                <span className="dc__organization__header__details__item__label">
                  {t("organizations.details.rpnt")}
                </span>
                <span className="dc__organization__header__details__item__value">
                  <RpntBadge rpnt={organization.rpnt} siret={organization.siret} />
                </span>
              </div>
            )}
            {organization && (
            <div className="dc__organization__header__details__item">
                <span className="dc__organization__header__details__item__label">
                  {t("organizations.details.contact")}
                </span>
                <span className="dc__organization__header__details__item__value dc__organization__header__details__item__value--contact">
                  <div>
                    {organization.site_internet ? (
                      <a href={organization.site_internet} target="_blank" rel="noopener noreferrer">
                        {organization.site_internet.replace("https://", "").replace("http://", "").replace("www.", "").replace(/\/$/, "")}
                      </a>
                    ) : (
                      <span>{t("organizations.details.website_missing")}</span>
                    )}
                  </div>
                  <div>
                    {organization.adresse_messagerie ? (
                      <a href={`mailto:${organization.adresse_messagerie}`}>{organization.adresse_messagerie}</a>
                    ) : (
                      <span>{t("organizations.details.email_missing")}</span>
                    )}
                  </div>
                </span>
              </div>
            )}
          </div>
        </div>
        <div>
          <div className="dc__organization__header__image"></div>
        </div>
      </div>
      <div className="dc__organization__tabs">
        <button
          className={`dc__organization__tabs__tab ${activeTab === "services" ? "dc__organization__tabs__tab--active" : ""}`}
          onClick={() => setActiveTab("services")}
        >
          {t("organizations.tabs.services")}
        </button>
        <button
          className={`dc__organization__tabs__tab ${activeTab === "accounts" ? "dc__organization__tabs__tab--active" : ""}`}
          onClick={() => setActiveTab("accounts")}
        >
          {t("organizations.tabs.accounts")}
        </button>
      </div>
      {activeTab === "services" && (
        <div
          className={`dc__services__list ${
            isServicesFetching ? "dc__services__list--fetching" : ""
          }`}
        >
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
      )}
      {activeTab === "accounts" && (
        <AccountsTab
          operatorId={operatorId}
          organizationId={organizationId}
        />
      )}
    </Container>
  );
}

Organization.getLayout = getGlobalExplorerLayout;
