import {
  Button,
  Input,
  Modal,
  ModalSize,
  Select,
} from "@openfun/cunningham-react";
import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Spinner } from "@gouvfr-lasuite/ui-kit";
import { Account } from "@/features/api/Repository";
import {
  useMutationCreateAccount,
  useMutationUpdateAccount,
  useMutationUpdateAccountServiceLink,
  useOrganizationServices,
} from "@/hooks/useQueries";

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
  const [roles, setRoles] = useState("");
  const [serviceLinkRoles, setServiceLinkRoles] = useState<
    Record<string, string>
  >({});
  const [isLoading, setIsLoading] = useState(false);

  // Reset form when account changes or modal opens
  useEffect(() => {
    if (isOpen) {
      if (account) {
        setEmail(account.email);
        setExternalId(account.external_id || "");
        setType(account.type);
        setRoles(account.roles?.join(", ") || "");
        const initialServiceRoles: Record<string, string> = {};
        account.service_links?.forEach((link) => {
          initialServiceRoles[link.service.id] = link.roles?.join(", ") || "";
        });
        setServiceLinkRoles(initialServiceRoles);
      } else {
        setEmail("");
        setExternalId("");
        setType("user");
        setRoles("");
        setServiceLinkRoles({});
      }
    }
  }, [account, isOpen]);

  const activeServices = services?.results?.filter(
    (s) => s.subscription?.is_active
  );

  const getServiceLinkRoles = (serviceId: string) => {
    if (serviceLinkRoles[serviceId] !== undefined) {
      return serviceLinkRoles[serviceId];
    }
    if (account) {
      const link = account.service_links?.find(
        (l) => l.service.id === serviceId
      );
      return link?.roles?.join(", ") || "";
    }
    return "";
  };

  const parseRoles = (rolesStr: string): string[] => {
    return rolesStr
      .split(",")
      .map((r) => r.trim())
      .filter(Boolean);
  };

  const updateServiceLinks = (accountId: string): Promise<void> => {
    const serviceUpdates = Object.entries(serviceLinkRoles)
      .filter(([, rolesStr]) => !isEditMode || rolesStr.trim() !== "" || isEditMode)
      .map(
        ([serviceId, rolesStr]) =>
          new Promise<void>((resolve, reject) => {
            updateServiceLink(
              {
                operatorId,
                organizationId,
                accountId,
                serviceId,
                data: { roles: parseRoles(rolesStr) },
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

    const parsedRoles = parseRoles(roles);

    if (isEditMode && account) {
      // Edit mode: update existing account
      updateAccount(
        {
          operatorId,
          organizationId,
          accountId: account.id,
          data: { roles: parsedRoles },
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
            roles: parsedRoles,
          },
        },
        {
          onSuccess: (newAccount) => {
            const nonEmptyServiceRoles = Object.entries(serviceLinkRoles).filter(
              ([, rolesStr]) => rolesStr.trim() !== ""
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

          <Input
            label={t("accounts.fields.roles")}
            value={roles}
            onChange={(e) => setRoles(e.target.value)}
            fullWidth
            text={t("accounts.fields.roles_help")}
          />

          {activeServices && activeServices.length > 0 && (
            <div className="dc__accounts__edit__services">
              <h4 className="dc__accounts__edit__services__title">
                {t("accounts.edit_modal.service_roles")}
              </h4>
              {activeServices.map((service) => (
                <Input
                  key={service.id}
                  label={service.name}
                  value={getServiceLinkRoles(service.id)}
                  onChange={(e) =>
                    setServiceLinkRoles((prev) => ({
                      ...prev,
                      [service.id]: e.target.value,
                    }))
                  }
                  fullWidth
                  text={t("accounts.fields.roles_help")}
                />
              ))}
            </div>
          )}
        </div>
      </form>
    </Modal>
  );
};
