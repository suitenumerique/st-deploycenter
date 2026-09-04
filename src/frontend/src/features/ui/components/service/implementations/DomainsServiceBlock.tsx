import {
  DomainWebsiteConfig,
  Organization,
  Service,
} from "@/features/api/Repository";
import {
  ServiceBlock,
  useServiceBlock,
} from "@/features/ui/components/service/ServiceBlock";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Icon, IconSize } from "@gouvfr-lasuite/ui-kit";
import { useModal } from "@openfun/cunningham-react";
import { MutateOptions } from "@tanstack/react-query";
import { ServiceAttribute } from "../ServiceAttribute";
import { DomainsModal } from "../DomainsModal";

const PREFIX = "organizations.services.types.domains";

/**
 * The Domains service block: the domains an organization declares for itself, and
 * what serves each one's website. Stored in the subscription metadata as
 * {domains, website}.
 */
export const DomainsServiceBlock = (props: {
  service: Service;
  organization: Organization;
}) => {
  const { t } = useTranslation();
  const blockProps = useServiceBlock(props.service, props.organization);
  const domainsModal = useModal();
  const [showDomainError, setShowDomainError] = useState(false);

  const subscription = props.service.subscription;

  const domains = useMemo(() => {
    const value = subscription?.metadata?.domains;
    return Array.isArray(value) ? (value as string[]) : [];
  }, [subscription?.metadata?.domains]);

  const website = useMemo(() => {
    const value = subscription?.metadata?.website;
    return (value ?? {}) as DomainWebsiteConfig;
  }, [subscription?.metadata?.website]);

  const handleSave = (
    newDomains: string[],
    newWebsite: DomainWebsiteConfig,
    options?: MutateOptions<unknown, unknown, unknown, unknown>
  ) => {
    if (newDomains.length > 0) {
      setShowDomainError(false);
    }
    blockProps.onChangeSubscription(
      {
        metadata: {
          ...subscription?.metadata,
          domains: newDomains,
          website: newWebsite,
        },
      },
      options
    );
  };

  // Activating without a single domain would subscribe to nothing.
  const canActivateSubscription = async () => {
    if (domains.length === 0) {
      setShowDomainError(true);
      return false;
    }
    return true;
  };

  return (
    <ServiceBlock
      {...blockProps}
      canActivateSubscription={canActivateSubscription}
      content={
        <div className="dc__service__attribute__container">
          {domainsModal.isOpen && (
            <DomainsModal
              {...domainsModal}
              organizationId={props.organization.id}
              instanceName={props.service.instance_name}
              domains={domains}
              website={website}
              onSave={handleSave}
            />
          )}
          <ServiceAttribute
            name={t(`${PREFIX}.domains.label`)}
            interactive={!blockProps.isManagedByOtherOperator}
            onClick={() => domainsModal.open()}
            value={
              domains.length > 0 ? (
                <span className="dc__domains-list">
                  {domains.map((domain) => (
                    <span key={domain}>{domain}</span>
                  ))}
                </span>
              ) : (
                t(`${PREFIX}.domains.empty`)
              )
            }
          />
          {showDomainError && domains.length === 0 && (
            <div className="dc__service__warning">
              <Icon name="warning" size={IconSize.SMALL} />
              {t(`${PREFIX}.warning`)}
            </div>
          )}
        </div>
      }
    />
  );
};
