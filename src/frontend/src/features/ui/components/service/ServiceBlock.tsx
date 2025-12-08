import { Organization, ServiceSubscription } from "@/features/api/Repository";
import { useTranslation } from "react-i18next";
import { Service } from "@/features/api/Repository";
import { Button, Switch, Tooltip, useModals } from "@openfun/cunningham-react";
import { Icon, IconSize } from "@gouvfr-lasuite/ui-kit";
import { useEffect, useState } from "react";
import { useMutationUpdateOrganizationServiceSubscription } from "@/hooks/useQueries";
import { useOperatorContext } from "@/features/layouts/components/GlobalLayout";
import { MutateOptions } from "@tanstack/react-query";

export const useServiceBlock = (
  service: Service,
  organization: Organization
) => {
  const [checked, setChecked] = useState(
    service.subscription ? service.subscription.is_active : false
  );
  const { mutate: updateOrganizationServiceSubscription } =
    useMutationUpdateOrganizationServiceSubscription();
  const { operatorId } = useOperatorContext();

  useEffect(() => {
    setChecked(service.subscription ? service.subscription.is_active : false);
  }, [service.subscription]);

  const onChangeSubscription = (
    data: Partial<ServiceSubscription>,
    options?: MutateOptions
  ) => {
    updateOrganizationServiceSubscription(
      {
        operatorId,
        organizationId: organization.id,
        serviceId: service.id,
        data,
      },
      options as Parameters<typeof updateOrganizationServiceSubscription>[1]
    );
  };

  const canActivateSubscription = async () => {
    return true;
  };

  return {
    service,
    organization,
    checked,
    setChecked,
    onChangeSubscription,
    canActivateSubscription,
  };
};

export const ServiceBlock = ({
  service,
  organization,
  checked,
  setChecked,
  onChangeSubscription,
  content,
  canActivateSubscription,
  showGoto = true,
}: {
  service: Service;
  organization: Organization;
  content?: React.ReactNode;
  showGoto?: boolean;
} & ReturnType<typeof useServiceBlock>) => {
  const { t } = useTranslation();
  const modals = useModals();
  const isExternallyManaged =
    service.operator_config?.externally_managed === true;

  const canSwitch = !isExternallyManaged && service.can_activate;

  return (
    <div
      className={`dc__service__block ${
        isExternallyManaged ? "dc__service__block--disabled" : ""
      }`}
    >
      <div className="dc__service__block__header">
        <div className="dc__service__block__header__title">
          {service.logo && (
            <div className="dc__service__block__header__logo">
              <img src={service.logo} alt={service.name} />
            </div>
          )}
          <div className="dc__service__block__header__name">{service.name}</div>
        </div>
        {canSwitch ? (
          <Switch
            checked={checked}
            onChange={async (e) => {
              if (e.target.checked) {
                if (!(await canActivateSubscription())) {
                  return;
                }
                const decision = await modals.confirmationModal();
                if (decision === "yes") {
                  onChangeSubscription(
                    { is_active: true },
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
                  onChangeSubscription(
                    { is_active: false },
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
        ) : (
          <Tooltip
            content={t(
              isExternallyManaged
                ? "organizations.services.externally_managed"
                : "organizations.services.cannot_activate"
            )}
          >
            <div
              className="dc__service__block__switch-wrapper"
              role="button"
              tabIndex={0}
              aria-label={t("organizations.services.externally_managed")}
            >
              <Switch checked={checked} disabled={true} />
            </div>
          </Tooltip>
        )}
      </div>
      <div className="dc__service__block__body">
        {!!service.description && (
          <div className="dc__service__block__description">
            {service.description}
          </div>
        )}
        <div className="dc__service__block__body__content">
          {content}
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
          {showGoto && service.url && (
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
