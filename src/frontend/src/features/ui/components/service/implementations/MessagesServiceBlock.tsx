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
import { useEffect, useMemo, useRef, useState } from "react";
import { useMessagesAdminCount, useOrganizationServices } from "@/hooks/useQueries";
import { useOperatorContext } from "@/features/layouts/components/GlobalLayout";
import { Icon, IconSize, Spinner } from "@gouvfr-lasuite/ui-kit";
import {
  Button,
  Checkbox,
  Modal,
  ModalSize,
  useModal,
} from "@openfun/cunningham-react";
import { useRouter } from "next/router";
import { MutateOptions } from "@tanstack/react-query";

const PREFIX = "organizations.services.types.messages";

export const MessagesServiceBlock = (props: {
  service: Service;
  organization: Organization;
}) => {
  const { t } = useTranslation();
  const router = useRouter();
  const { operatorId } = useOperatorContext();
  const blockProps = useServiceBlock(props.service, props.organization);
  const domainModal = useModal();
  const [showDomainError, setShowDomainError] = useState(false);

  // Get domains from subscription metadata if available
  // Returns undefined if not set, or the array (possibly empty) if explicitly configured
  const savedDomains = useMemo(() => {
    const domainsData = props.service.subscription?.metadata?.domains;
    if (domainsData && Array.isArray(domainsData)) {
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
    if (pcDomains && Array.isArray(pcDomains)) {
      return pcDomains as string[];
    }
    return [];
  }, [services]);

  // Use saved domains if explicitly set (even if empty), otherwise fall back to ProConnect domains
  const domains = savedDomains !== undefined ? savedDomains : proConnectDomains;
  const hasDomains = domains.length > 0;

  const navigateToAccounts = (role: string) => {
    router.push({
      pathname: router.pathname,
      query: { ...router.query, tab: "accounts", role },
    });
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
              proConnectDomains={proConnectDomains}
              onSave={handleDomainsChange}
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
          <a
            href="#"
            className="dc__service__admins-summary__link"
            onClick={(e) => {
              e.preventDefault();
              navigateToAccounts(`service.${props.service.id}.admin`);
            }}
          >
            {t(`${PREFIX}.admins.service_count`, { count: serviceAdminCount })}
          </a>
          {" "}{t(`${PREFIX}.admins.and`)}{" "}
          <a
            href="#"
            className="dc__service__admins-summary__link"
            onClick={(e) => {
              e.preventDefault();
              navigateToAccounts("org.admin");
            }}
          >
            {t(`${PREFIX}.admins.global_count`, { count: globalAdminCount })}
          </a>
        </div>
      }
    />
  );
};

/**
 * Domain Selector Modal
 */
const DomainSelectorModal = (props: {
  isOpen: boolean;
  onClose: () => void;
  domains: string[];
  proConnectDomains: string[];
  onSave: (
    domains: string[],
    options?: MutateOptions<unknown, unknown, unknown, unknown>
  ) => void;
}) => {
  const { t } = useTranslation();
  const [selectedDomains, setSelectedDomains] = useState<string[]>(props.domains);
  const [isPending, setIsPending] = useState(false);
  const [showSpinner, setShowSpinner] = useState(false);
  const spinnerTimeout = useRef<ReturnType<typeof setTimeout>>(undefined);

  // Combine existing domains and ProConnect domains for the list
  const allDomains = useMemo(() => {
    const combined = new Set([...props.domains, ...props.proConnectDomains]);
    return Array.from(combined).sort();
  }, [props.domains, props.proConnectDomains]);

  useEffect(() => {
    return () => clearTimeout(spinnerTimeout.current);
  }, []);

  const handleToggleDomain = (domain: string) => {
    setSelectedDomains((prev) =>
      prev.includes(domain)
        ? prev.filter((d) => d !== domain)
        : [...prev, domain]
    );
  };

  const handleSubmit = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();

    // Check if selection differs from what was passed in
    const sortedSelected = [...selectedDomains].sort();
    const sortedOriginal = [...props.domains].sort();
    const hasChanged =
      sortedSelected.length !== sortedOriginal.length ||
      !sortedSelected.every((d, i) => d === sortedOriginal[i]);

    if (hasChanged) {
      setIsPending(true);
      spinnerTimeout.current = setTimeout(() => setShowSpinner(true), 600);

      props.onSave(selectedDomains, {
        onSuccess: () => {
          clearTimeout(spinnerTimeout.current);
          setIsPending(false);
          setShowSpinner(false);
          props.onClose();
        },
        onError: () => {
          clearTimeout(spinnerTimeout.current);
          setIsPending(false);
          setShowSpinner(false);
        },
      });
    } else {
      props.onClose();
    }
  };

  return (
    <Modal
      size={ModalSize.MEDIUM}
      title={t(`${PREFIX}.domains.modal.title`)}
      closeOnEsc={!isPending}
      closeOnClickOutside={!isPending}
      isOpen={props.isOpen}
      onClose={props.onClose}
      rightActions={
        <>
          <Button
            type="button"
            onClick={props.onClose}
            color="secondary"
            disabled={isPending}
          >
            {t("common.cancel")}
          </Button>
          <Button
            type="submit"
            form="domain-selector-form"
            disabled={isPending}
            icon={showSpinner ? <Spinner /> : undefined}
          >
            {t("common.save")}
          </Button>
        </>
      }
    >
      <div className="dc__service__attribute__modal__content">
        <p className="dc__service__attribute__modal__content__help">
          {t(`${PREFIX}.domains.modal.description`)}
        </p>
        <form id="domain-selector-form" onSubmit={handleSubmit}>
          <div className="dc__domain-selector">
            <div className="dc__domain-selector__list">
              {allDomains.map((domain) => (
                <div key={domain} className="dc__domain-selector__item">
                  <Checkbox
                    label={domain}
                    checked={selectedDomains.includes(domain)}
                    onChange={() => handleToggleDomain(domain)}
                  />
                </div>
              ))}
              {allDomains.length === 0 && (
                <p className="dc__domain-selector__empty">
                  {t(`${PREFIX}.domains.modal.no_domains`)}
                </p>
              )}
            </div>
                      </div>
        </form>
      </div>
    </Modal>
  );
};
