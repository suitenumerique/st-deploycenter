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
import {
  createOrganizationServiceSubscription,
  deleteOrganizationServiceSubscription,
  Service,
} from "@/features/api/Repository";
import { Switch, useModals } from "@openfun/cunningham-react";
import { Breadcrumbs } from "@/features/ui/components/breadcrumbs/Breadcrumbs";
import { useEffect, useState } from "react";

export default function Organization() {
  const router = useRouter();
  const operatorId = router.query.operator_id as string;
  const organizationId = router.query.id as string;
  const { t } = useTranslation();
  const { data: operator } = useOperator(operatorId);

  const { data: organization } = useOrganization(organizationId);
  const { data: services } = useOrganizationServices(organizationId);

  useEffect(() => {
    if (services?.results?.length && services.results.length > 0) {
      const service = services.results[0]!;
      // createOrganizationServiceSubscription(organizationId, service.id);
      // createOrganizationServiceSubscription(
      //   "eae355c0-f890-4a4a-9bc8-594f3b1dd544",
      //   service.id
      // );
    }
  }, [services]);

  console.log("services", services);

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
        {services?.results.map((service) => (
          <ServiceBlock
            key={service.id}
            service={service}
            organizationId={organizationId}
          />
        ))}
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
                createOrganizationServiceSubscription({
                  organizationId,
                  serviceId: service.id,
                });
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
                deleteOrganizationServiceSubscription({
                  organizationId,
                  serviceId: service.id,
                  subscriptionId: service.subscription.id,
                });
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
