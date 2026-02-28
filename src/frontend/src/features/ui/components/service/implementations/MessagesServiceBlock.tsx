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
import { useTranslation } from "react-i18next";
import { useMemo, useState } from "react";
import { useMessagesAdminCount, useOrganizationServices } from "@/hooks/useQueries";
import { useOperatorContext } from "@/features/layouts/components/GlobalLayout";
import { useAuth } from "@/features/auth/Auth";
import { Icon, IconSize } from "@gouvfr-lasuite/ui-kit";
import { useModal } from "@openfun/cunningham-react";
import Link from "next/link";
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

  // Fetch admin count
  const { data: adminCount } = useMessagesAdminCount(
    operatorId,
    props.organization.id,
    props.service.id
  );

  // Fetch services to get ProConnect domains as default
  const { data: services } = useOrganizationServices(
    operatorId,
    props.organization.id
  );

  // Get default domains from ProConnect service
  const proConnectDomains = useMemo(() => {
    const proConnectService = services?.results?.find(
      (s) => s.type === SERVICE_TYPE_PROCONNECT
    );
    const pcDomains = proConnectService?.subscription?.metadata?.domains;
    if (Array.isArray(pcDomains)) {
      return pcDomains as string[];
    }
    return [];
  }, [services]);

  // Use saved domains if explicitly set (even if empty), otherwise fall back to ProConnect domains
  const domains = savedDomains !== undefined ? savedDomains : proConnectDomains;
  const hasDomains = domains.length > 0;

  const getAccountsUrl = (role: string) => {
    return `/operators/${operatorId}/organizations/${props.organization.id}?tab=accounts&role=${encodeURIComponent(role)}`;
  };

  // Block activation if no domains are configured
  const canActivateSubscription = async () => {
    if (!hasDomains) {
      setShowDomainError(true);
      return false;
    }
    return true;
  };

  const serviceAdminCount = adminCount?.serviceCount ?? 0;
  const globalAdminCount = adminCount?.globalCount ?? 0;

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
        <div className="dc__service__admins-summary">
          {t(`${PREFIX}.admins.label`)} :{" "}
          <Link
            href={getAccountsUrl(`service.${props.service.id}.admin`)}
            className="dc__service__admins-summary__link"
          >
            {t(`${PREFIX}.admins.service_count`, { count: serviceAdminCount })}
          </Link>
          {" "}{t(`${PREFIX}.admins.and`)}{" "}
          <Link
            href={getAccountsUrl("org.admin")}
            className="dc__service__admins-summary__link"
          >
            {t(`${PREFIX}.admins.global_count`, { count: globalAdminCount })}
          </Link>
        </div>
      }
    />
  );
};
