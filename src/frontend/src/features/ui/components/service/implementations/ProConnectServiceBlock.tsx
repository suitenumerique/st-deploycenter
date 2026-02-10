import {
  MailDomainStatus,
  OperatorIdp,
  Organization,
  Service,
  ServiceSubscription,
} from "@/features/api/Repository";
import { useOperatorContext } from "@/features/layouts/components/GlobalLayout";
import { useMemo } from "react";
import {
  ServiceBlock,
  useServiceBlock,
} from "@/features/ui/components/service/ServiceBlock";
import { Controller, useForm } from "react-hook-form";
import {
  Button,
  Modal,
  ModalSize,
  Select,
  useModal,
} from "@openfun/cunningham-react";
import { ServiceAttribute } from "../ServiceAttribute";
import { Icon, IconSize } from "@gouvfr-lasuite/ui-kit";

/**
 * Helper function to get ProConnect message and icon based on organization and subscription state
 */

type ProConnectMessage = {
  text?: React.ReactNode;
  alert?:React.ReactNode,
  icon?: string,
  disabled?: boolean
};

const getProConnectMessage = (
  organization: Organization,
  subscriptionDomains: string[] | null,
  isActive: boolean
): ProConnectMessage => {

  const emailSetupMessage = <>Vous devez probablement raccorder ce domaine au fournisseur de messagerie, puis <a href="https://suiteterritoriale.anct.gouv.fr/conformite/referentiel#2.1" target="_blank" rel="noopener noreferrer">déclarer le nouvel email de contact.</a></>;

  // Show active subscription message if subscription is active
  if (subscriptionDomains && subscriptionDomains.length > 0) {

    const domainsList = subscriptionDomains.map((domain, idx) => <>{!!idx && <span>, </span>}<b>{domain}</b></>);
    if (isActive) {
      const message: ProConnectMessage = {};
      if (subscriptionDomains.length === 1) {
        message.text = <span>Le domaine {domainsList} est actuellement routé vers ce FI.</span>;
      } else {
        message.text = <span>Les domaines {domainsList} sont actuellement routés vers ce FI.</span>;
      }

      // If the domain is unknown to the RPNT, ask for declaration
      if (organization.mail_domain_status !== MailDomainStatus.VALID || subscriptionDomains[0] != organization.mail_domain) {
        message.alert = <span>Le domaine {domainsList} n&apos;est pas présent dans l&apos;adresse de messagerie déclarée sur Service-Public.gouv.fr. Vous devez la <a href="https://suiteterritoriale.anct.gouv.fr/conformite/referentiel#2.1" target="_blank" rel="noopener noreferrer">mettre à jour</a> pour assurer la conformité au RPNT.</span>;
        message.icon = "warning";
      }

      return message;

    // Manage the case where sub is inactive and we had previous domain(s) that are not the single one we can
    // add here automatically.
    } else if (!(subscriptionDomains.length == 1 && subscriptionDomains[0] === organization.mail_domain)) {
      if (subscriptionDomains.length === 1) {
        return {
          alert: <span>Le domaine {domainsList} était précédemment utilisé pour ProConnect.<br/> Veuillez contacter le support ANCT pour effectuer une migration.</span>,
          icon: "warning",
          disabled: true,
        };
      } else {
        return {
          alert: <span>Les domaines {domainsList} étaient précédemment utilisés pour ProConnect.<br/> Veuillez contacter le support ANCT pour effectuer une migration.</span>,
          icon: "warning",
          disabled: true,
        };
      }
    }
  }

  // Use the server-computed status to determine the appropriate message
  switch (organization.mail_domain_status) {
    case MailDomainStatus.NEED_EMAIL_SETUP:
      return {
        text: <span>Le domaine <b>{organization.mail_domain}</b>, actuellement utilisé pour le site internet, sera routé vers ce FI.</span>,
        alert: <span>
          {emailSetupMessage}
          <br/>Si ce domaine ne convient pas, veuillez contacter le support ANCT.
        </span>,
        icon: "info"
      };
    case MailDomainStatus.INVALID:
      return {
        alert: <span>Aucun nom de domaine valide n&apos;est connu. Vous devez d&apos;abord en <a href="https://suiteterritoriale.anct.gouv.fr/conformite/referentiel#1.1" target="_blank" rel="noopener noreferrer">déclarer un</a>.</span>,
        icon: "warning",
        disabled: true,
      };
    case MailDomainStatus.VALID:
      return {
        text: <span>Le domaine <b>{organization.mail_domain}</b> sera routé vers ce FI.</span>,
        alert: <span>Si ce domaine ne convient pas, veuillez contacter le support ANCT.</span>,
        icon: "info"
      };
    default:
      return {
        alert: <span>Situation inconnue. Veuillez contacter le support ANCT.</span>,
        icon: "warning",
        disabled: true,
      };
  }
};

/**
 * Handles the ProConnect service block.
 *
 * There are two independents flows:
 *
 * - Activate the subscription
 *   When trying to activate the subscription, we need to validate the data first via canActivateSubscription.
 *   That's why we use a form to validate the data, so it's a future proof solution for future potentially
 *   more complicated validation rules.
 *
 * - Update the IDP
 *   When updating the IDP, we need to save the change to the backend independently
 *   of the form validation. ( Because we setup the IDP before activating the subscription )
 *   It's not possible to update the IDP after activating the subscription.
 */
export const ProConnectServiceBlock = (props: {
  service: Service;
  organization: Organization;
}) => {
  const { operator } = useOperatorContext();
  const blockProps = useServiceBlock(props.service, props.organization);
  const subscription = props.service.subscription;

  // Use the subscription's operator IDPs to display the correct IDP name,
  // even when viewing a subscription managed by another operator.
  // Fallback to current operator's IDPs when no subscription exists yet,
  // so the user can select an IDP before creating the subscription.
  const availableIdps = subscription?.operator_idps ?? operator?.config.idps ?? [];
  const getIdp = (idp_id: string) => {
    return availableIdps.find((idp) => idp.id == idp_id);
  };

  // Get domains from subscription metadata if available
  const subscriptionDomains = useMemo(() => {
    const domains = subscription?.metadata?.domains;
    if (domains && Array.isArray(domains) && domains.length > 0) {
      return domains;
    }
    return null;
  }, [subscription?.metadata?.domains]);

  const {
    handleSubmit,
    control,
    formState: { errors },
  } = useForm({
    defaultValues: {
      mail_domain: props.organization.mail_domain,
      idp_id: subscription?.metadata?.idp_id,
    },
  });

  const saveIdpChange = (idp?: OperatorIdp) => {
    const data: Partial<ServiceSubscription> = {
      metadata: {idp_id: idp?.id},
    };
    if (!subscription || blockProps.isManagedByOtherOperator) {
      data.is_active = false;
    }
    blockProps.onChangeSubscription(data);
  };

  const idpModal = useModal();

  // Check if subscription is less than 48 hours old
  const isSubscriptionLessThan48Hours = useMemo(() => {
    if (!subscription?.created_at) {
      return false;
    }
    const createdAt = new Date(subscription.created_at);
    const now = new Date();
    const diffInHours = (now.getTime() - createdAt.getTime()) / (1000 * 60 * 60);
    return diffInHours < 48;
  }, [subscription?.created_at]);

  const message = getProConnectMessage(
    props.organization,
    subscriptionDomains,
    subscription?.is_active || false
  );

  return (
    <ServiceBlock
      {...blockProps}
      showGoto={false}
      confirmationText={<>
        <span>En activant ProConnect, vous garantissez que :</span>
        <ul>
          <li>l&apos;annuaire <b>complet</b> des utilisateurs de ce domaine est présent dans le FI sélectionné,</li>
          <li>les utilisateurs sont capables de se connecter à leur compte,</li>
          <li>des procédures sont en place pour maintenir cet annuaire à jour.</li>
        </ul>
      </>}
      canActivateSubscription={async () => {
        if (message.disabled) {
          return false;
        }
        return new Promise((resolve) => {
          handleSubmit(
            () => resolve(true),
            () => resolve(false)
          )();
        });
      }}
      content={
        <>
          <form>
            <div className="dc__service__attribute__container">

              <Controller
                control={control}
                name="idp_id"
                rules={{ required: true }}
                render={({ field: { value, onChange } }) => (
                  <>
                    <Modal
                      size={ModalSize.SMALL}
                      title="Modification du FI"
                      closeOnEsc={true}
                      closeOnClickOutside={true}
                      {...idpModal}
                      rightActions={
                        <>
                          <Button type="submit" onClick={idpModal.close}>
                            Fermer
                          </Button>
                        </>
                      }
                    >
                      <div className="dc__service__attribute__modal__content">
                        <p className="dc__service__attribute__modal__content__help">
                          Sélectionnez un FI pour l&apos;organisation.
                        </p>
                        <Select
                          label="Fournisseur d'Identité"
                          value={value}
                          onChange={(e) => {
                            const idp = getIdp(e.target.value as string);
                            onChange(idp?.id || "");
                            saveIdpChange(idp);
                          }}
                          options={
                            availableIdps.map((idp) => ({
                              label: idp.name,
                              value: idp.id,
                            }))
                          }
                        />
                      </div>
                    </Modal>
                    <ServiceAttribute
                      name="Fournisseur d'Identité"
                      interactive={!subscription?.is_active && !blockProps.isManagedByOtherOperator}
                      onClick={() => idpModal.open()}
                      value={
                        getIdp(value)?.name ??
                        "Aucun"
                      }
                    >
                      {errors.idp_id?.type === "required" && (
                        <p
                          role="alert"
                          className="dc__service__attribute__error"
                        >
                          Vous devez sélectionner un FI.
                        </p>
                      )}
                    </ServiceAttribute>
                    
                  </>
                )}
              />     

              {message.text && <ServiceAttribute>
                <div className="dc__service__attribute_text">{message.text}</div>
              </ServiceAttribute>}
              
              {message.alert && message.icon && <div className={message.icon == "warning" ? "dc__service__warning" : "dc__service__info"}>
                  <Icon name={message.icon} size={IconSize.SMALL} />
                  {message.alert}
              </div>}

              {isSubscriptionLessThan48Hours && subscription?.is_active && (
                <div className="dc__service__info">
                  <Icon name="info" size={IconSize.SMALL} />
                  L&apos;activation de ProConnect peut prendre jusqu&apos;à 48 heures
                </div>
              )}

            </div>
          </form>
          {props.service.config?.help_center_url && (
            <div className="dc__service__block__goto">
              <a target="_blank" href={props.service.config?.help_center_url}>
                Centre de ressources
              </a>
              <Button
                color="tertiary"
                size="nano"
                href={props.service.config?.help_center_url}
                target="_blank"
                icon={<Icon name="open_in_new" size={IconSize.X_SMALL} />}
              ></Button>
            </div>
          )}
        </>
      }
    />
  );
};
