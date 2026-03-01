import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Icon, IconSize, Spinner } from "@gouvfr-lasuite/ui-kit";
import { Button, Input, Modal, ModalSize } from "@openfun/cunningham-react";
import { MutateOptions } from "@tanstack/react-query";

const PREFIX = "organizations.services.types.messages";

export type DomainSelectorModalProps = {
  isOpen: boolean;
  onClose: () => void;
  domains: string[];
  suggestedDomains?: string[];
  isSuperUser: boolean;
  onSave: (
    domains: string[],
    options?: MutateOptions<unknown, unknown, unknown, unknown>
  ) => void;
};

export const DomainSelectorModal = (props: DomainSelectorModalProps) => {
  const { t } = useTranslation();
  const hasSavedDomains = props.domains.length > 0;
  const [currentDomains, setCurrentDomains] = useState<string[]>(props.domains);
  const [extraDomains, setExtraDomains] = useState<string[]>([]);
  const [newDomainInput, setNewDomainInput] = useState("");
  const [isPending, setIsPending] = useState(false);
  const [showSpinner, setShowSpinner] = useState(false);
  const [saveError, setSaveError] = useState(false);
  const spinnerTimeout = useRef<ReturnType<typeof setTimeout>>(undefined);

  const suggestedDomains = props.suggestedDomains ?? [];

  // Sync currentDomains when props.domains changes (e.g., after external update)
  useEffect(() => {
    setCurrentDomains(props.domains);
  }, [props.domains]);

  // Only show suggestions when no domains are saved yet (first-time setup)
  const allDomains = useMemo(() => {
    const suggestions = hasSavedDomains ? [] : suggestedDomains;
    const combined = new Set([...currentDomains, ...suggestions, ...extraDomains]);
    return Array.from(combined).sort();
  }, [currentDomains, suggestedDomains, extraDomains, hasSavedDomains]);

  useEffect(() => {
    return () => clearTimeout(spinnerTimeout.current);
  }, []);

  const handleDeleteDomain = (domain: string) => {
    setCurrentDomains((prev) => prev.filter((d) => d !== domain));
    setExtraDomains((prev) => prev.filter((d) => d !== domain));
  };

  const handleAddDomain = () => {
    const domain = newDomainInput.trim().toLowerCase();
    if (!domain || !domain.includes(".")) return;
    if (!currentDomains.includes(domain)) {
      setCurrentDomains((prev) => [...prev, domain]);
    }
    if (!allDomains.includes(domain)) {
      setExtraDomains((prev) => [...prev, domain]);
    }
    setNewDomainInput("");
  };

  const handleSubmit = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();

    // Check if domains differ from what was passed in
    const sortedCurrent = [...currentDomains].sort();
    const sortedOriginal = [...props.domains].sort();
    const hasChanged =
      sortedCurrent.length !== sortedOriginal.length ||
      !sortedCurrent.every((d, i) => d === sortedOriginal[i]);

    if (hasChanged) {
      setIsPending(true);
      setSaveError(false);
      spinnerTimeout.current = setTimeout(() => setShowSpinner(true), 600);

      props.onSave(currentDomains, {
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
          setSaveError(true);
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
      onClose={isPending ? () => {} : props.onClose}
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
                  <span className="dc__domain-selector__item__name">{domain}</span>
                  {props.isSuperUser && (
                    <Button
                      size="small"
                      color="secondary"
                      icon={<Icon name="delete" />}
                      className="dc__domain-selector__item__delete"
                      title={t(`${PREFIX}.domains.modal.delete_label`)}
                      onClick={() => handleDeleteDomain(domain)}
                    />
                  )}
                </div>
              ))}
              {allDomains.length === 0 && (
                <p className="dc__domain-selector__empty">
                  {t(`${PREFIX}.domains.modal.no_domains`)}
                </p>
              )}
            </div>
            {props.isSuperUser ? (
              <div className="dc__domain-selector__add">
                <Input
                  label=""
                  placeholder={t(`${PREFIX}.domains.modal.add_placeholder`)}
                  value={newDomainInput}
                  onChange={(e) => setNewDomainInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      handleAddDomain();
                    }
                  }}
                />
                <Button
                  type="button"
                  color="secondary"
                  onClick={handleAddDomain}
                  disabled={!newDomainInput.trim().includes(".")}
                >
                  {t(`${PREFIX}.domains.modal.add_button`)}
                </Button>
              </div>
            ) : (
              <div className="dc__service__info">
                <Icon name="info" size={IconSize.SMALL} />
                {t(`${PREFIX}.domains.modal.contact_support`)}
              </div>
            )}
            {saveError && (
              <p className="dc__domain-selector__error">
                {t("api.error.unexpected")}
              </p>
            )}
          </div>
        </form>
      </div>
    </Modal>
  );
};
