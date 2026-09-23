import { Organization, Service } from "@/features/api/Repository";
import {
  ServiceBlock,
  useServiceBlock,
} from "@/features/ui/components/service/ServiceBlock";
import { ServiceAttribute } from "../ServiceAttribute";
import { ServiceAdminsFooter } from "../ServiceAdminsFooter";
import { ChoiceModal } from "../ChoiceModal";
import {
  ADMIN_MODE_ALL,
  AutoAdminAttribute,
  getAutoAdminMode,
  saveSubscriptionMetadata,
} from "./ExtendedAdminServiceBlock";
import { Trans, useTranslation } from "react-i18next";
import { Icon, IconSize, useModal } from "@gouvfr-lasuite/ui-components";

const PREFIX = "organizations.services.types.bal";

const DELEGATION_ALLOWED = "allowed";
const DELEGATION_REFUSED = "refused";

// Whether the commune lets its EPCI administer its addresses
// (epci_delegation metadata, allowed unless explicitly false).
const EpciDelegationAttribute = (props: {
  service: Service;
  organization: Organization;
  blockProps: ReturnType<typeof useServiceBlock>;
}) => {
  const { t } = useTranslation();
  const modal = useModal();
  const delegation =
    props.service.subscription?.metadata?.epci_delegation === false
      ? DELEGATION_REFUSED
      : DELEGATION_ALLOWED;

  return (
    <>
      {modal.isOpen && (
        <ChoiceModal
          {...modal}
          title={t(`${PREFIX}.epci_delegation.modal.title`)}
          description={
            <Trans
              i18nKey={`${PREFIX}.epci_delegation.modal.description`}
              values={{
                epci_name:
                  props.organization.epci_libelle ??
                  props.organization.epci_siren,
                service_name: props.service.name,
              }}
              components={{ bold: <strong /> }}
            />
          }
          name="epci-delegation"
          value={delegation}
          choices={[DELEGATION_ALLOWED, DELEGATION_REFUSED].map((choice) => ({
            value: choice,
            label: t(`${PREFIX}.epci_delegation.choices.${choice}.label`),
            description: t(
              `${PREFIX}.epci_delegation.choices.${choice}.description`
            ),
          }))}
          onSave={(value, options) =>
            saveSubscriptionMetadata(
              props.service,
              props.blockProps.onChangeSubscription,
              { epci_delegation: value === DELEGATION_ALLOWED },
              options
            )
          }
        />
      )}
      <ServiceAttribute
        name={t(`${PREFIX}.epci_delegation.label`)}
        value={t(`${PREFIX}.epci_delegation.choices.${delegation}.short`)}
        onClick={() => modal.open()}
        interactive={!props.blockProps.isManagedByOtherOperator}
      />
    </>
  );
};

export const BalServiceBlock = (props: {
  service: Service;
  organization: Organization;
}) => {
  const { t } = useTranslation();
  const blockProps = useServiceBlock(props.service, props.organization);
  const isCommune = props.organization.type === "commune";
  // Auto-admin only applies to communes: EPCI admins are explicit only.
  const hideServiceCount =
    isCommune &&
    getAutoAdminMode(props.organization, props.service).mode ===
      ADMIN_MODE_ALL;

  const showEpciNote =
    props.organization.type === "epci" &&
    (props.service.subscription?.is_active ?? false);

  return (
    <ServiceBlock
      {...blockProps}
      content={
        <div className="dc__service__attribute__container">
          {isCommune && (
            <>
              <AutoAdminAttribute
                service={props.service}
                organization={props.organization}
                blockProps={blockProps}
              />
              {props.organization.epci_siren && (
                <EpciDelegationAttribute
                  service={props.service}
                  organization={props.organization}
                  blockProps={blockProps}
                />
              )}
            </>
          )}
          {showEpciNote && (
            <div className="dc__service__info">
              <Icon name="info" size={IconSize.SMALL} />
              {t(`${PREFIX}.epci_note`)}
            </div>
          )}
        </div>
      }
      footer={
        <ServiceAdminsFooter
          organization={props.organization}
          service={props.service}
          hideServiceCount={hideServiceCount}
        />
      }
    />
  );
};
