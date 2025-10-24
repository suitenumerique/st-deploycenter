import { Container } from "@/features/layouts/components/container/Container";
import {
  getGlobalExplorerLayout,
  useOperatorContext,
} from "@/features/layouts/components/GlobalLayout";
import { useRouter } from "next/router";
import {
  useMutationCreateOrganizationServiceSubscription,
  useMutationDeleteOrganizationServiceSubscription,
  useOrganization,
  useOrganizationServices,
} from "@/hooks/useQueries";
import { useTranslation } from "react-i18next";
import { Service } from "@/features/api/Repository";
import { Button, Switch, useModals } from "@openfun/cunningham-react";
import { Breadcrumbs } from "@/features/ui/components/breadcrumbs/Breadcrumbs";
import { useState } from "react";
import { useBreadcrumbOperator } from "@/features/ui/components/breadcrumbs/Parts";
import { Icon, IconSize, Spinner } from "@gouvfr-lasuite/ui-kit";

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
        {isServicesLoading ? (
          <Spinner />
        ) : (
          services?.results.map((service) => (
            <ServiceBlock
              key={service.id}
              service={service}
              organizationId={organizationId}
            />
          ))
        )}
      </div>
    </Container>
  );
}

const ServiceBlock = ({
  service,
  organizationId,
}: {
  service: Service;
  organizationId: string;
}) => {
  const { t } = useTranslation();
  const [checked, setChecked] = useState(!!service.subscription);
  const { mutate: deleteOrganizationServiceSubscription } =
    useMutationDeleteOrganizationServiceSubscription();
  const { mutate: createOrganizationServiceSubscription } =
    useMutationCreateOrganizationServiceSubscription();
  const modals = useModals();
  const { operatorId } = useOperatorContext();
  return (
    <div className="dc__service__block">
      <div className="dc__service__block__header">
        {service.logo ? (
          <div className="dc__service__block__header__logo">
            <img src={service.logo} alt={service.name} />
          </div>
        ) : (
          <div className="dc__service__block__header__name">{service.name}</div>
        )}
        <Switch
          checked={checked}
          onChange={async (e) => {
            if (e.target.checked) {
              const decision = await modals.confirmationModal();
              if (decision === "yes") {
                createOrganizationServiceSubscription(
                  {
                    operatorId,
                    organizationId,
                    serviceId: service.id,
                  },
                  {
                    onError: () => {
                      setChecked(false);
                    },
                  }
                );
                setChecked(true);
              }
            } else {
              const decision = await modals.deleteConfirmationModal({
                title: t("organizations.services.disable_modal.title"),
                children: t("organizations.services.disable_modal.content", {
                  service: service.name,
                }),
              });
              if (decision === "delete") {
                deleteOrganizationServiceSubscription(
                  {
                    operatorId,
                    organizationId,
                    serviceId: service.id,
                    subscriptionId: service.subscription.id,
                  },
                  {
                    onError: () => {
                      setChecked(true);
                    },
                  }
                );
                setChecked(false);
              }
            }
          }}
        />
      </div>
      <div className="dc__service__block__body">
        <div className="dc__service__block__description">
          {service.description}
        </div>
        <div className="dc__service__block__body__content">
          {/*
          <div className="dc__service__block__values">
            <div className="dc__service__block__values__item">
              <span className="dc__service__block__values__item__label">
                {t("organizations.services.values.users")}
              </span>
              <span className="dc__service__block__values__item__value">
                0
              </span>
            </div>
          </div>
          */}
          {service.url && (
            <div className="dc__service__block__goto">
              <a target="_blank" href={service.url}>
                {t("organizations.services.goto")}
              </a>
              <Button
                color="tertiary"
                size="nano"
                href={service.url}
                target="_blank"
                icon={<Icon name="open_in_new" size={IconSize.X_SMALL} />}
              ></Button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

Organization.getLayout = getGlobalExplorerLayout;
