import {
  Organization,
  Service,
  SERVICE_TYPE_PROCONNECT,
} from "@/features/api/Repository";
import {
  ServiceBlock,
  useServiceBlock,
} from "@/features/ui/components/service/ServiceBlock";
import { ServiceAttribute } from "../ServiceAttribute";
import { ServiceAdminsFooter } from "../ServiceAdminsFooter";
import { useTranslation } from "react-i18next";
import { useMemo, useState } from "react";
import { useOrganizationServices } from "@/hooks/useQueries";
import { useOperatorContext } from "@/features/layouts/components/GlobalLayout";
import { useAuth } from "@/features/auth/Auth";
import { Icon, IconSize } from "@gouvfr-lasuite/ui-kit";
import { useModal } from "@openfun/cunningham-react";
import { MutateOptions } from "@tanstack/react-query";
import { DomainSelectorModal } from "../DomainSelectorModal";

const PREFIX = "organizations.services.types.messages";

export const MessagesServiceBlock = (props: {
  service: Service;
  organization: Organization;
}) => {
  const { t } = useTranslation();
  const { operatorId } = useOperatorContext();
  const { user } = useAuth();
  const isSuperUser = user?.is_superuser ?? false;
  const blockProps = useServiceBlock(props.service, props.organization);
  const domainModal = useModal();
  const [showDomainError, setShowDomainError] = useState(false);

  // Get domains from subscription metadata if available
  // Returns undefined if not set, or the array (possibly empty) if explicitly configured
  const savedDomains = useMemo(() => {
    const domainsData = props.service.subscription?.metadata?.domains;
    if (Array.isArray(domainsData)) {
      return domainsData as string[];
    }
    return undefined;
  }, [props.service.subscription?.metadata?.domains]);

  // Fetch services to get ProConnect domains as default
  const { data: services } = useOrganizationServices(
    operatorId,
    props.organization.id
  );

  // Get default domains from all ProConnect services
  const proConnectDomains = useMemo(() => {
    const proConnectServices = services?.results?.filter(
      (s) => s.type === SERVICE_TYPE_PROCONNECT
    ) ?? [];
    const domains = proConnectServices.flatMap((s) => {
      const pcDomains = s.subscription?.metadata?.domains;
      if (Array.isArray(pcDomains)) {
        return pcDomains as string[];
      }
      return [];
    });
    return Array.from(new Set(domains)).sort();
  }, [services]);

  // Use saved domains if explicitly set (even if empty), otherwise fall back to ProConnect domains
  const domains = savedDomains !== undefined ? savedDomains : proConnectDomains;
  const hasDomains = domains.length > 0;

  // Block activation if no domains are configured
  const canActivateSubscription = async () => {
    if (!hasDomains) {
      setShowDomainError(true);
      return false;
    }
    return true;
  };

  const handleDomainsChange = (
    newDomains: string[],
    options?: MutateOptions<unknown, unknown, unknown, unknown>
  ) => {
    if (newDomains.length > 0) {
      setShowDomainError(false);
    }
    blockProps.onChangeSubscription(
      {
        metadata: {
          ...props.service.subscription?.metadata,
          domains: newDomains,
        },
      },
      options
    );
  };

  // Provide domains when activating (uses current domains which may be ProConnect defaults)
  const getActivationData = () => ({
    metadata: {
      ...props.service.subscription?.metadata,
      domains,
    },
  });

  return (
    <ServiceBlock
      {...blockProps}
      canActivateSubscription={canActivateSubscription}
      getActivationData={getActivationData}
      showEntitlementsBeforeSubscription={true}
      content={
        <div className="dc__service__attribute__container">
          {domainModal.isOpen && (
            <DomainSelectorModal
              {...domainModal}
              domains={domains}
              suggestedDomains={proConnectDomains}
              onSave={handleDomainsChange}
              isSuperUser={isSuperUser}
            />
          )}
          <ServiceAttribute
            name={t(`${PREFIX}.domains.label`)}
            value={
              hasDomains
                ? <span className="dc__domains-list">
                    {domains.map((domain) => (
                      <span key={domain}>{domain}</span>
                    ))}
                  </span>
                : t(`${PREFIX}.domains.empty`)
            }
            interactive={!blockProps.isManagedByOtherOperator}
            onClick={() => domainModal.open()}
          />
          {showDomainError && !hasDomains && (
            <div className="dc__service__warning">
              <Icon name="warning" size={IconSize.SMALL} />
              {t(`${PREFIX}.domains.warning`)}
            </div>
          )}
        </div>
      }
      footer={
        <ServiceAdminsFooter
          organization={props.organization}
          service={props.service}
        />
      }
    />
  );
};
