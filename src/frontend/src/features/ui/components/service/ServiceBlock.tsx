import {
  Entitlement,
  Organization,
  ServiceSubscription,
} from "@/features/api/Repository";
import { useTranslation } from "react-i18next";
import { Service } from "@/features/api/Repository";
import {
  Button,
  Switch,
  Tooltip,
  useModals,
} from "@openfun/cunningham-react";
import { Icon, IconSize } from "@gouvfr-lasuite/ui-kit";
import { useEffect, useState } from "react";
import { useMutationUpdateOrganizationServiceSubscription } from "@/hooks/useQueries";
import { useOperatorContext } from "@/features/layouts/components/GlobalLayout";
import { MutateOptions } from "@tanstack/react-query";
import { StoragePickerEntitlementField } from "./entitlements/fields/StoragePickerEntitlementField";

export type EntitlementFields = {
  fields: Record<string, { type: string }>;
};

export type EntitlementsFields = Record<string, EntitlementFields>;

/**
 * This map defines the fields for the entitlements of a service block.
 *
 * It goes:
 * {
 *  <service_type>: {
 *    entitlements: {
 *      <entitlement_type>: {
 *        fields: [
 *          {
 *            <field_name>: {
 *              type: <field_type>,
 *            },
 *          },
 *        ],
 *      },
 *    },
 *  },
 * }
 *
 */
const ENTITLEMENTS_FIELDS: Record<
  string,
  {
    entitlements: EntitlementsFields;
  }
> = {
  drive: {
    entitlements: {
      drive_storage: {
        fields: {
          max_storage: {
            type: "storage_picker",
          },
        },
      },
    },
  },
};

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

  const entitlementsFields =
    ENTITLEMENTS_FIELDS[service.type]?.entitlements || {};

  return {
    service,
    organization,
    checked,
    setChecked,
    onChangeSubscription,
    canActivateSubscription,
    entitlementsFields,
  };
};

type ServiceBlockProps = {
  service: Service;
  organization: Organization;
  content?: React.ReactNode;
  showGoto?: boolean;
  entitlementsFields?: EntitlementsFields;
} & ReturnType<typeof useServiceBlock>;

export const ServiceBlock = (props: ServiceBlockProps) => {
  const { t } = useTranslation();
  const modals = useModals();
  const isExternallyManaged =
    props.service.operator_config?.externally_managed === true;
  const isPopulationLimitExceeded =
    props.service.activation_blocked_reason === "population_limit_exceeded";
  const isMissingRequiredServices =
    props.service.activation_blocked_reason === "missing_required_services";
  const canSwitch = !isExternallyManaged && props.service.can_activate;

  return (
    <div
      className={`dc__service__block ${
        !canSwitch
          ? "dc__service__block--disabled"
          : ""
      }`}
    >
      <div className="dc__service__block__header">
        <div className="dc__service__block__header__title">
          {props.service.logo && (
            <div className="dc__service__block__header__logo">
              <a href={props.service.url} target="_blank" rel="noopener noreferrer">
                <img src={props.service.logo} alt={props.service.name} />
              </a>
            </div>
          )}
          <div className="dc__service__block__header__name-wrapper">
            <div className="dc__service__block__header__name">
              {props.service.name}
            </div>
            {props.service.instance_name && (
              <div className="dc__service__block__header__instance_name">
                <a href={props.service.url} target="_blank" rel="noopener noreferrer">
                  {props.service.instance_name}
                </a>
              </div>
            )}
          </div>
        </div>
        {canSwitch ? (
          <Switch
            checked={props.checked}
            onChange={async (e) => {
              if (e.target.checked) {
                if (!(await props.canActivateSubscription())) {
                  return;
                }
                const decision = await modals.confirmationModal();
                if (decision === "yes") {
                  props.onChangeSubscription(
                    { is_active: true },
                    {
                      onError: () => {
                        props.setChecked(false);
                      },
                    }
                  );
                  props.setChecked(true);
                }
              } else {
                const decision = await modals.deleteConfirmationModal({
                  title: t("organizations.services.disable_modal.title"),
                  children: t("organizations.services.disable_modal.content", {
                    service: props.service.name,
                  }),
                });
                if (decision === "delete") {
                  props.onChangeSubscription(
                    { is_active: false },
                    {
                      onError: () => {
                        props.setChecked(true);
                      },
                    }
                  );
                  props.setChecked(false);
                }
              }
            }}
          />
        ) : (
          <Tooltip
            content={t(
              isExternallyManaged
                ? "organizations.services.externally_managed"
                : isPopulationLimitExceeded
                  ? "organizations.services.population_limit_exceeded"
                  : isMissingRequiredServices
                    ? "organizations.services.missing_required_services"
                  : "organizations.services.cannot_activate"
            )}
          >
            <div
              className="dc__service__block__switch-wrapper"
              role="button"
              tabIndex={0}
              aria-label={
                isExternallyManaged
                  ? t("organizations.services.externally_managed")
                  : isPopulationLimitExceeded
                    ? t("organizations.services.population_limit_exceeded")
                    : isMissingRequiredServices
                      ? t("organizations.services.missing_required_services")
                    : t("organizations.services.cannot_activate")
              }
            >
              <Switch checked={props.checked} disabled={true} />
            </div>
          </Tooltip>
        )}
      </div>
      <div className="dc__service__block__body">
        {!!props.service.description && !props.service.subscription && (
          <div className="dc__service__block__description">
            {props.service.description}
          </div>
        )}
        <div className="dc__service__block__body__content">
          {props.content}
          {Object.keys(props.entitlementsFields).length > 0 && (
            <ServiceBlockEntitlements {...props} />
          )}
          {props.showGoto && props.service.url && (
            <div className="dc__service__block__goto">
              <a target="_blank" href={props.service.url}>
                {t("organizations.services.goto")}
              </a>
              <Button
                color="tertiary"
                size="nano"
                href={props.service.url}
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

const ServiceBlockEntitlements = (props: ServiceBlockProps) => {
  return (
    <div className="dc__service__block__entitlements">
      {Object.entries(props.entitlementsFields).map(
        ([entitlementType, entitlementFields]) => (
          <ServiceBlockEntitlement
            key={entitlementType}
            entitlementName={entitlementType}
            entitlementFields={entitlementFields}
            {...props}
          />
        )
      )}
    </div>
  );
};

type ServiceBlockEntitlementProps = {
  entitlementName: string;
  entitlementFields: EntitlementFields;
} & ServiceBlockProps;

const ServiceBlockEntitlement = (props: ServiceBlockEntitlementProps) => {
  const entitlement = props.service.subscription?.entitlements?.find(
    (e) => e.type === props.entitlementName
  );
  if (!entitlement) {
    return null;
  }
  return (
    <div className="dc__service__block__entitlement">
      <div className="dc__service__block__entitlement__fields">
        {Object.entries(props.entitlementFields.fields).map(
          ([fieldName, field]) => {
            return (
              <ServiceBlockEntitlementField
                key={fieldName}
                fieldName={fieldName}
                field={field}
                entitlement={entitlement}
                {...props}
              />
            );
          }
        )}
      </div>
    </div>
  );
};

export type ServiceBlockEntitlementFieldProps = {
  fieldName: string;
  field: { type: string };
  entitlement: Entitlement;
} & ServiceBlockEntitlementProps;

const ServiceBlockEntitlementField = (
  props: ServiceBlockEntitlementFieldProps
) => {
  switch (props.field.type) {
    case "storage_picker":
      return <StoragePickerEntitlementField {...props} />;
    default:
      return <div>Unknown field type: {props.field.type}</div>;
  }
};
