import { Organization, Service } from "@/features/api/Repository";
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
import { DomainMultiSelectModal } from "../DomainMultiSelectModal";
import { MutateOptions } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

const PREFIX = "organizations.services.types.proconnect";

/**
 * ProConnect status message. Same for every user; superusers just additionally
 * get the domain editor (an action button), not a different message.
 */

type ProConnectMessage = {
  text?: React.ReactNode;
  alert?: React.ReactNode;
  icon?: string;
  disabled?: boolean;
};

const RPNT_REFERENTIEL_URL =
  "https://suiteterritoriale.anct.gouv.fr/conformite/referentiel";

const getProConnectMessage = (
  organization: Organization,
  subscriptionDomains: string[] | null,
  isActive: boolean,
  idpId: string | undefined
): ProConnectMessage => {
  // Active subscription: no text. The card already lists these domains in its
  // "Domaines" row and the toggle already says the service is on, so naming them
  // again adds nothing. Only the conformity warning below is worth saying.
  if (isActive && subscriptionDomains && subscriptionDomains.length > 0) {
    const message: ProConnectMessage = {};
    // Conformity is per routed domain: every one of them must be declared on
    // service-public.gouv.fr (the "dpnt" bucket), not just the first.
    const declared = new Set(organization.proconnect_domains?.dpnt ?? []);
    const undeclared = subscriptionDomains.filter((d) => !declared.has(d));
    const conformant = organization.type === "other" || undeclared.length === 0;
    if (!conformant) {
      const pluralUndeclared = undeclared.length > 1;
      message.alert = (
        <span>
          {pluralUndeclared ? "Les domaines " : "Le domaine "}
          <b>{undeclared.join(", ")}</b>
          {pluralUndeclared
            ? " ne sont pas déclarés"
            : " n'est pas déclaré"}{" "}
          sur Service-Public.gouv.fr.{" "}
          <a href={`${RPNT_REFERENTIEL_URL}#2.1`} target="_blank" rel="noopener noreferrer">
            {pluralUndeclared ? "Mettez-les à jour" : "Mettez-le à jour"}
          </a>{" "}
          pour assurer la conformité au RPNT.
        </span>
      );
      message.icon = "warning";
    }
    return message;
  }

  // Inactive: announce what activation would actually route, resolved the same
  // way the backend does it (serializers._validate_proconnect_subscription) —
  // the subscription's own domains when it has any, the RPNT mail domain
  // otherwise. Reading mail_domain directly would name a domain that is not the
  // one routed whenever a superuser has set the list explicitly.
  const pending =
    subscriptionDomains ??
    (organization.mail_domain ? [organization.mail_domain] : []);

  // Nothing to route: the backend refuses the activation, so block it here too.
  if (pending.length === 0) {
    return {
      alert: (
        <span>
          Aucun nom de domaine valide n&apos;est connu. Vous devez d&apos;abord en{" "}
          <a href={`${RPNT_REFERENTIEL_URL}#1.1`} target="_blank" rel="noopener noreferrer">
            déclarer un
          </a>
          .
        </span>
      ),
      icon: "warning",
      disabled: true,
    };
  }

  // api-partenaires refuses a PATCH carrying a domain absent from the provider's
  // *deployed* allowlist, so activating would fail with
  // attached_email_domain_not_allowed. Only when we actually know that allowlist
  // for this idp: an unknown one (no entry) must not block on a guess. An empty
  // one is known — it means nothing is pre-validated yet.
  const deployed = idpId ? organization.proconnect_prevalidated?.[idpId] : undefined;
  const notYet = deployed ? pending.filter((d) => !deployed.includes(d)) : [];
  if (notYet.length > 0) {
    const pluralNotYet = notYet.length > 1;
    return {
      alert: (
        <span>
          {pluralNotYet ? "Les domaines " : "Le domaine "}
          <b>{notYet.join(", ")}</b>
          {pluralNotYet ? " ne sont pas encore pré-validés" : " n'est pas encore pré-validé"}{" "}
          pour ce fournisseur d&apos;identité. L&apos;activation sera refusée tant
          que la liste d&apos;autorisation déployée ne les contient pas.
        </span>
      ),
      icon: "warning",
      disabled: true,
    };
  }

  const pluralPending = pending.length > 1;
  return {
    text: (
      <span>
        {pluralPending ? "Les domaines " : "Le domaine "}
        <b>{pending.join(", ")}</b>
        {pluralPending ? " seront routés" : " sera routé"} vers ce FI.
      </span>
    ),
    icon: "info",
  };
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
  const { t } = useTranslation();
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

  const message = getProConnectMessage(
    props.organization,
    subscriptionDomains,
    subscription?.is_active || false,
    idpId
  );

  // Activation requires an IDP to be configured on the service.
  const canActivateSubscription = async () => {
    // No superuser bypass: `disabled` now means "the backend will refuse this"
    // — no domain to route (400), or a domain the provider's deployed allowlist
    // does not carry (the push 502s and rolls back). A superuser fixes those in
    // the domains modal first, which clears the flag.
    if (message.disabled) {
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

              {domainModal.isOpen && (
                <DomainMultiSelectModal
                  {...domainModal}
                  organization={props.organization}
                  instanceName={props.service.instance_name}
                  idpId={props.service.config?.idp_id}
                  isActive={subscription?.is_active ?? false}
                  routed={domains}
                  onSave={handleDomainsChange}
                />
              )}
              <ServiceAttribute
                name={t(`${PREFIX}.domains.label`)}
                interactive={!blockProps.isManagedByOtherOperator}
                onClick={() => domainModal.open()}
                value={
                  domains.length > 0
                    ? <span className="dc__domains-list">
                        {domains.map((domain) => (
                          <span key={domain}>{domain}</span>
                        ))}
                      </span>
                    : t(`${PREFIX}.domains.empty`)
                }
              />

              {message.text && <ServiceAttribute>
                <div className="dc__service__attribute_text">{message.text}</div>
              </ServiceAttribute>}

              {message.alert && message.icon && <div className={message.icon == "warning" ? "dc__service__warning" : "dc__service__info"}>
                  <Icon name={message.icon} size={IconSize.SMALL} />
                  {message.alert}
              </div>}

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
