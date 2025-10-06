import { Container } from "@/features/layouts/components/container/Container";
import { getGlobalExplorerLayout } from "@/features/layouts/components/GlobalLayout";
import { useRouter } from "next/router";
import useOperator, {
  useMutationCreateOrganizationServiceSubscription,
  useMutationDeleteOrganizationServiceSubscription,
  useOrganization,
  useOrganizationServices,
} from "@/hooks/useQueries";
import { useTranslation } from "react-i18next";
import { Service } from "@/features/api/Repository";
import { Switch, useModals } from "@openfun/cunningham-react";
import { Breadcrumbs } from "@/features/ui/components/breadcrumbs/Breadcrumbs";
import { useState } from "react";
import { useBreadcrumbOperator } from "@/features/ui/components/breadcrumbs/Parts";
import { Spinner } from "@gouvfr-lasuite/ui-kit";

export default function Organization() {
  const router = useRouter();
  const operatorId = router.query.operator_id as string;
  const organizationId = router.query.id as string;
  const { t } = useTranslation();
  const { data: operator, isLoading: isOperatorLoading } =
    useOperator(operatorId);
  const { data: organization, isLoading: isOrganizationLoading } =
    useOrganization(organizationId);
  const { data: services, isLoading: isServicesLoading } =
    useOrganizationServices(organizationId);
  const breadcrumbOperator = useBreadcrumbOperator(
    operatorId,
    operator,
    isOperatorLoading
  );

  return (
    <Container>
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
      <div className="dc__container__content__title--small">
        {t("organizations.services.title")}
      </div>
      <div className="dc__container__content__subtitle">
        {t("organizations.services.subtitle")}
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
  return (
    <div className="dc__service__block">
      <div className="dc__service__block__name">{service.name}</div>
      <div className="dc__service__block__description">
        {service.description}
      </div>
      <div className="dc__service__block__status">
        <Switch
          labelSide="right"
          label={t("organizations.services.status")}
          checked={checked}
          onChange={async (e) => {
            if (e.target.checked) {
              const decision = await modals.confirmationModal();
              if (decision === "yes") {
                createOrganizationServiceSubscription(
                  {
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
    </div>
  );
};

Organization.getLayout = getGlobalExplorerLayout;
