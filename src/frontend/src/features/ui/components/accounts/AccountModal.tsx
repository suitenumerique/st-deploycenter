import {
  Button,
  Checkbox,
  Input,
  Modal,
  ModalSize,
  Select,
} from "@openfun/cunningham-react";
import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Spinner } from "@gouvfr-lasuite/ui-kit";
import { Account, Service } from "@/features/api/Repository";
import {
  useMutationCreateAccount,
  useMutationUpdateAccount,
  useMutationUpdateAccountServiceLink,
  useOrganizationServices,
} from "@/hooks/useQueries";
import { GLOBAL_ROLES, getServiceRoles } from "@/features/accounts/roles";

interface AccountModalProps {
  operatorId: string;
  organizationId: string;
  account?: Account | null;
  isOpen: boolean;
  onClose: () => void;
}

export const AccountModal = ({
  operatorId,
  organizationId,
  account,
  isOpen,
  onClose,
}: AccountModalProps) => {
  const { t } = useTranslation();
  const isEditMode = !!account;

  const { mutate: createAccount } = useMutationCreateAccount();
  const { mutate: updateAccount } = useMutationUpdateAccount();
  const { mutate: updateServiceLink } = useMutationUpdateAccountServiceLink();
  const { data: services } = useOrganizationServices(
    operatorId,
    organizationId
  );

  const [email, setEmail] = useState("");
  const [externalId, setExternalId] = useState("");
  const [type, setType] = useState("user");
  const [globalRoles, setGlobalRoles] = useState<string[]>([]);
  const [serviceLinkRoles, setServiceLinkRoles] = useState<
    Record<string, string[]>
  >({});
  const [isLoading, setIsLoading] = useState(false);

  // Reset form when account changes or modal opens
  useEffect(() => {
    if (isOpen) {
      if (account) {
        setEmail(account.email);
        setExternalId(account.external_id || "");
        setType(account.type);
        setGlobalRoles(account.roles || []);
        const initialServiceRoles: Record<string, string[]> = {};
        account.services?.forEach((link) => {
          initialServiceRoles[link.service.id] = link.roles || [];
        });
        setServiceLinkRoles(initialServiceRoles);
      } else {
        setEmail("");
        setExternalId("");
        setType("user");
        setGlobalRoles([]);
        setServiceLinkRoles({});
      }
    }
  }, [account, isOpen]);

  // Show all services configured for this operator, not just active ones
  const configuredServices = services?.results?.filter(
    (s) => s.operator_config
  );

  const getServiceLinkRolesArray = (serviceId: string): string[] => {
    if (serviceLinkRoles[serviceId] !== undefined) {
      return serviceLinkRoles[serviceId];
    }
    if (account) {
      const link = account.services?.find(
        (l) => l.service.id === serviceId
      );
      return link?.roles || [];
    }
    return [];
  };

  const toggleGlobalRole = (role: string) => {
    setGlobalRoles((prev) =>
      prev.includes(role) ? prev.filter((r) => r !== role) : [...prev, role]
    );
  };

  const toggleServiceRole = (serviceId: string, role: string) => {
    setServiceLinkRoles((prev) => {
      const currentRoles = prev[serviceId] || getServiceLinkRolesArray(serviceId);
      const newRoles = currentRoles.includes(role)
        ? currentRoles.filter((r) => r !== role)
        : [...currentRoles, role];
      return { ...prev, [serviceId]: newRoles };
    });
  };

  const updateServiceLinks = (accountId: string): Promise<void> => {
    const serviceUpdates = Object.entries(serviceLinkRoles).map(
      ([serviceId, roles]) =>
        new Promise<void>((resolve, reject) => {
          updateServiceLink(
            {
              operatorId,
              organizationId,
              accountId,
              serviceId,
              data: { roles },
            },
            {
              onSuccess: () => resolve(),
              onError: (err) => reject(err),
            }
          );
        })
    );

    if (serviceUpdates.length === 0) {
      return Promise.resolve();
    }

    return Promise.all(serviceUpdates).then(() => {});
  };

  const submit = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setIsLoading(true);

    if (isEditMode && account) {
      // Edit mode: update existing account
      updateAccount(
        {
          operatorId,
          organizationId,
          accountId: account.id,
          data: { roles: globalRoles },
        },
        {
          onSuccess: () => {
            updateServiceLinks(account.id)
              .then(() => {
                setIsLoading(false);
                onClose();
              })
              .catch(() => {
                setIsLoading(false);
              });
          },
          onError: () => {
            setIsLoading(false);
          },
        }
      );
    } else {
      // Add mode: create new account
      createAccount(
        {
          operatorId,
          organizationId,
          data: {
            email,
            external_id: externalId,
            type,
            roles: globalRoles,
          },
        },
        {
          onSuccess: (newAccount) => {
            const nonEmptyServiceRoles = Object.entries(serviceLinkRoles).filter(
              ([, roles]) => roles.length > 0
            );

            if (nonEmptyServiceRoles.length === 0) {
              setIsLoading(false);
              onClose();
              return;
            }

            updateServiceLinks(newAccount.id)
              .then(() => {
                setIsLoading(false);
                onClose();
              })
              .catch(() => {
                setIsLoading(false);
              });
          },
          onError: () => {
            setIsLoading(false);
          },
        }
      );
    }
  };

  const formId = isEditMode ? "edit-account-form" : "add-account-form";

  const renderRoleCheckboxes = (
    roles: string[],
    availableRoles: { value: string; labelKey: string }[],
    onToggle: (role: string) => void
  ) => {
    return (
      <div className="dc__accounts__modal__roles__checkboxes">
        {availableRoles.map((roleDef) => (
          <Checkbox
            key={roleDef.value}
            label={t(roleDef.labelKey)}
            checked={roles.includes(roleDef.value)}
            onChange={() => onToggle(roleDef.value)}
          />
        ))}
      </div>
    );
  };

  const renderServiceRoles = (service: Service) => {
    const serviceRoles = getServiceRoles(service.type);
    // Skip services with no roles defined
    if (serviceRoles.length === 0) {
      return null;
    }
    const currentRoles = getServiceLinkRolesArray(service.id);

    return (
      <div key={service.id} className="dc__accounts__modal__roles__group">
        <h5 className="dc__accounts__modal__roles__group__title">
          {service.name}
        </h5>
        {renderRoleCheckboxes(currentRoles, serviceRoles, (role) =>
          toggleServiceRole(service.id, role)
        )}
      </div>
    );
  };

  return (
    <Modal
      size={ModalSize.MEDIUM}
      title={
        isEditMode
          ? t("accounts.edit_modal.title")
          : t("accounts.add_modal.title")
      }
      isOpen={isOpen}
      onClose={onClose}
      closeOnEsc={true}
      closeOnClickOutside={true}
      rightActions={
        <>
          <Button
            type="button"
            onClick={onClose}
            color="secondary"
            disabled={isLoading}
          >
            {t("common.cancel")}
          </Button>
          <Button
            type="submit"
            form={formId}
            disabled={isLoading || (!isEditMode && !email)}
            icon={isLoading ? <Spinner /> : undefined}
            iconPosition="right"
          >
            {t("common.save")}
          </Button>
        </>
      }
    >
      <form id={formId} onSubmit={submit}>
        <div className="dc__accounts__modal__fields">
          {isEditMode ? (
            <>
              <div className="dc__accounts__edit__info">
                <span className="dc__accounts__edit__info__label">
                  {t("accounts.fields.email")}
                </span>
                <span className="dc__accounts__edit__info__value">
                  {account?.email}
                </span>
              </div>
              <div className="dc__accounts__edit__info">
                <span className="dc__accounts__edit__info__label">
                  {t("accounts.fields.external_id")}
                </span>
                <span className="dc__accounts__edit__info__value">
                  {account?.external_id || "-"}
                </span>
              </div>
              <div className="dc__accounts__edit__info">
                <span className="dc__accounts__edit__info__label">
                  {t("accounts.fields.type")}
                </span>
                <span className="dc__accounts__edit__info__value">
                  {account?.type}
                </span>
              </div>
            </>
          ) : (
            <>
              <Input
                label={t("accounts.fields.email")}
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                fullWidth
                required
              />
              <Input
                label={t("accounts.fields.external_id")}
                value={externalId}
                onChange={(e) => setExternalId(e.target.value)}
                fullWidth
              />
              <Select
                label={t("accounts.fields.type")}
                value={type}
                clearable={false}
                onChange={(e) => setType(e.target.value as string)}
                options={[
                  { label: t("accounts.filter.types.user"), value: "user" },
                  { label: t("accounts.filter.types.mailbox"), value: "mailbox" },
                ]}
              />
            </>
          )}

          <div className="dc__accounts__modal__roles">
            <div className="dc__accounts__modal__roles__group">
              <h5 className="dc__accounts__modal__roles__group__title">
                {t("accounts.roles.global_title")}
              </h5>
              {renderRoleCheckboxes(globalRoles, GLOBAL_ROLES, toggleGlobalRole)}
            </div>

            {configuredServices && configuredServices.length > 0 && (
              <>
                {configuredServices.map((service) => renderServiceRoles(service))}
              </>
            )}
          </div>
        </div>
      </form>
    </Modal>
  );
};
