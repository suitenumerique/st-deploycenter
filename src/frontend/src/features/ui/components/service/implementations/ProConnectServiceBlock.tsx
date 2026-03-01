import {
  MailDomainStatus,
  Organization,
  Service,
} from "@/features/api/Repository";
import { useAuth } from "@/features/auth/Auth";
import { useMemo } from "react";
import {
  ServiceBlock,
  useServiceBlock,
} from "@/features/ui/components/service/ServiceBlock";
import {
  Button,
  useModal,
} from "@openfun/cunningham-react";
import { ServiceAttribute } from "../ServiceAttribute";
import { Icon, IconSize } from "@gouvfr-lasuite/ui-kit";
import { DomainSelectorModal } from "../DomainSelectorModal";
import { MutateOptions } from "@tanstack/react-query";

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
      if (organization.type != "other") {
        if (organization.mail_domain_status !== MailDomainStatus.VALID || subscriptionDomains[0] != organization.mail_domain) {
          message.alert = <span>Le domaine {domainsList} n&apos;est pas présent dans l&apos;adresse de messagerie déclarée sur Service-Public.gouv.fr. Vous devez la <a href="https://suiteterritoriale.anct.gouv.fr/conformite/referentiel#2.1" target="_blank" rel="noopener noreferrer">mettre à jour</a> pour assurer la conformité au RPNT.</span>;
          message.icon = "warning";
        }
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
 * IDP is now stored in service.config.idp_id (immutable per service)
 * and displayed as read-only.
 */
export const ProConnectServiceBlock = (props: {
  service: Service;
  organization: Organization;
}) => {
  const { user } = useAuth();
  const isSuperUser = user?.is_superuser ?? false;
  const blockProps = useServiceBlock(props.service, props.organization);
  const subscription = props.service.subscription;
  const domainModal = useModal();

  const idpId = props.service.config?.idp_id;

  // Get domains from subscription metadata if available
  const subscriptionDomains = useMemo(() => {
    const domains = subscription?.metadata?.domains;
    if (domains && Array.isArray(domains) && domains.length > 0) {
      return domains;
    }
    return null;
  }, [subscription?.metadata?.domains]);

  const domains = subscriptionDomains ?? [];

  const handleDomainsChange = (
    newDomains: string[],
    options?: MutateOptions<unknown, unknown, unknown, unknown>
  ) => {
    blockProps.onChangeSubscription(
      {
        metadata: {
          ...subscription?.metadata,
          domains: newDomains,
        },
      },
      options
    );
  };

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

  // Activation requires an IDP to be configured on the service
  const canActivateSubscription = async () => {
    if (message.disabled && !isSuperUser) {
      return false;
    }
    if (!idpId) {
      return false;
    }
    return true;
  };

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
      canActivateSubscription={canActivateSubscription}
      content={
        <>
          <form>
            <div className="dc__service__attribute__container">

              {isSuperUser && (
                <>
                  {domainModal.isOpen && (
                    <DomainSelectorModal
                      {...domainModal}
                      domains={domains}
                      isSuperUser={isSuperUser}
                      onSave={handleDomainsChange}
                    />
                  )}
                  <ServiceAttribute
                    name="Domaines"
                    interactive={!blockProps.isManagedByOtherOperator}
                    onClick={() => domainModal.open()}
                    value={
                      domains.length > 0
                        ? <span className="dc__domains-list">
                            {domains.map((domain) => (
                              <span key={domain}>{domain}</span>
                            ))}
                          </span>
                        : "Aucun"
                    }
                  />
                </>
              )}

              {!isSuperUser && message.text && <ServiceAttribute>
                <div className="dc__service__attribute_text">{message.text}</div>
              </ServiceAttribute>}

              {!isSuperUser && message.alert && message.icon && <div className={message.icon == "warning" ? "dc__service__warning" : "dc__service__info"}>
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
