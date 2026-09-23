import {
  Organization,
  Service,
  ServiceSubscriptionInput,
} from "@/features/api/Repository";
import {
  ServiceBlock,
  useServiceBlock,
} from "@/features/ui/components/service/ServiceBlock";
import { ServiceAttribute } from "../ServiceAttribute";
import { ServiceAdminsFooter } from "../ServiceAdminsFooter";
import { ChoiceModal } from "../ChoiceModal";
import { Trans, useTranslation } from "react-i18next";
import { useModal } from "@gouvfr-lasuite/ui-components";
import { MutateOptions } from "@tanstack/react-query";

export const ADMIN_MODE_ALL = "all";
const ADMIN_MODE_MANUAL = "manual";
const DEFAULT_POPULATION_THRESHOLD = 3500;

const PREFIX = "organizations.services.extended_admin";

const computeDefaultMode = (
  organization: Organization,
  service: Service
): string => {
  const threshold =
    service.config?.auto_admin_population_threshold ??
    DEFAULT_POPULATION_THRESHOLD;
  if (
    organization.population != null &&
    organization.population < threshold
  ) {
    return ADMIN_MODE_ALL;
  }
  return ADMIN_MODE_MANUAL;
};

// The auto_admin mode of the subscription, or the population-based default.
export const getAutoAdminMode = (
  organization: Organization,
  service: Service
) => {
  const persistedMode = service.subscription?.metadata?.auto_admin as
    | string
    | undefined;
  return {
    mode: persistedMode ?? computeDefaultMode(organization, service),
    isDefault: !persistedMode,
  };
};

// Saves subscription metadata without activating a not-yet-active subscription.
export const saveSubscriptionMetadata = (
  service: Service,
  onChangeSubscription: ReturnType<
    typeof useServiceBlock
  >["onChangeSubscription"],
  metadata: Record<string, unknown>,
  options?: MutateOptions<unknown, unknown, unknown, unknown>
) => {
  const isActive = service.subscription?.is_active ?? false;
  const data: ServiceSubscriptionInput = {
    metadata,
    ...(!isActive && { is_active: false }),
  };
  onChangeSubscription(data, options);
};

export const AutoAdminAttribute = (props: {
  service: Service;
  organization: Organization;
  blockProps: ReturnType<typeof useServiceBlock>;
}) => {
  const { t } = useTranslation();
  const modal = useModal();
  const { mode, isDefault } = getAutoAdminMode(
    props.organization,
    props.service
  );

  const shortLabel = t(`${PREFIX}.choices.${mode}.short`);
  const displayValue = isDefault
    ? t(`${PREFIX}.default_short`, { value: shortLabel })
    : shortLabel;

  return (
    <>
      {modal.isOpen && (
        <ChoiceModal
          {...modal}
          title={t(`${PREFIX}.modal.title`)}
          description={
            <Trans
              i18nKey={`${PREFIX}.modal.description`}
              values={{ service_name: props.service.name }}
              components={{ bold: <strong /> }}
            />
          }
          name="admin-mode"
          value={mode}
          choices={[ADMIN_MODE_ALL, ADMIN_MODE_MANUAL].map((choice) => ({
            value: choice,
            label: t(`${PREFIX}.choices.${choice}.label`),
            description: t(`${PREFIX}.choices.${choice}.description`, {
              population: DEFAULT_POPULATION_THRESHOLD,
            }),
          }))}
          onSave={(newMode, options) =>
            saveSubscriptionMetadata(
              props.service,
              props.blockProps.onChangeSubscription,
              { auto_admin: newMode },
              options
            )
          }
        />
      )}
      <ServiceAttribute
        name={t(`${PREFIX}.label`)}
        value={displayValue}
        onClick={() => modal.open()}
        interactive={!props.blockProps.isManagedByOtherOperator}
      />
    </>
  );
};

export const ExtendedAdminServiceBlock = (props: {
  service: Service;
  organization: Organization;
}) => {
  const blockProps = useServiceBlock(props.service, props.organization);
  const { mode } = getAutoAdminMode(props.organization, props.service);

  return (
    <ServiceBlock
      {...blockProps}
      content={
        <div className="dc__service__attribute__container">
          <AutoAdminAttribute
            service={props.service}
            organization={props.organization}
            blockProps={blockProps}
          />
        </div>
      }
      footer={
        <ServiceAdminsFooter
          organization={props.organization}
          service={props.service}
          hideServiceCount={mode === ADMIN_MODE_ALL}
        />
      }
    />
  );
};
