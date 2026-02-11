import {
  Organization,
  Service,
} from "@/features/api/Repository";
import {
  ServiceBlock,
  useServiceBlock,
} from "@/features/ui/components/service/ServiceBlock";
import { ServiceAttribute } from "../ServiceAttribute";
import { Trans, useTranslation } from "react-i18next";
import {
  Button,
  Modal,
  ModalSize,
  Radio,
  RadioGroup,
  useModal,
} from "@openfun/cunningham-react";
import { Spinner } from "@gouvfr-lasuite/ui-kit";
import { useEffect, useRef, useState } from "react";
import { MutateOptions } from "@tanstack/react-query";

const ADMIN_MODE_ALL = "all";
const ADMIN_MODE_MANUAL = "manual";
const DEFAULT_POPULATION_THRESHOLD = 3500;

const PREFIX = "organizations.services.extended_admin";

const computeDefaultMode = (
  organization: Organization,
  service: Service
): string => {
  const threshold =
    service.config?.auto_admin_population_threshold ??
    DEFAULT_POPULATION_THRESHOLD;
  if (
    organization.population != null &&
    organization.population < threshold
  ) {
    return ADMIN_MODE_ALL;
  }
  return ADMIN_MODE_MANUAL;
};

export const ExtendedAdminServiceBlock = (props: {
  service: Service;
  organization: Organization;
}) => {
  const { t } = useTranslation();
  const blockProps = useServiceBlock(props.service, props.organization);
  const modal = useModal();
  const subscription = props.service.subscription;

  const persistedMode =
    subscription?.metadata?.auto_admin as
      | string
      | undefined;
  const isDefault = !persistedMode;
  const effectiveMode =
    persistedMode ?? computeDefaultMode(props.organization, props.service);

  const shortLabel = t(`${PREFIX}.choices.${effectiveMode}.short`);
  const displayValue = isDefault
    ? t(`${PREFIX}.default_short`, { value: shortLabel })
    : shortLabel;

  const isActive = subscription?.is_active ?? false;

  const handleSave = (
    newMode: string,
    options?: MutateOptions<unknown, unknown, unknown, unknown>
  ) => {
    blockProps.onChangeSubscription(
      {
        metadata: { auto_admin: newMode },
        ...(!isActive && { is_active: false }),
      },
      options
    );
  };

  return (
    <ServiceBlock
      {...blockProps}
      content={
        <div className="dc__service__attribute__container">
          {modal.isOpen && (
            <ExtendedAdminModal
              {...modal}
              mode={effectiveMode}
              onSave={handleSave}
              serviceName={props.service.name}
            />
          )}
          <ServiceAttribute
            name={t(`${PREFIX}.label`)}
            value={displayValue}
            onClick={() => modal.open()}
            interactive={!blockProps.isManagedByOtherOperator}
          />
        </div>
      }
    />
  );
};

const ExtendedAdminModal = (props: {
  isOpen: boolean;
  onClose: () => void;
  mode: string;
  onSave: (
    mode: string,
    options?: MutateOptions<unknown, unknown, unknown, unknown>
  ) => void;
  serviceName: string;
}) => {
  const { t } = useTranslation();
  const [selected, setSelected] = useState(props.mode);
  const [isPending, setIsPending] = useState(false);
  const [showSpinner, setShowSpinner] = useState(false);
  const spinnerTimeout = useRef<ReturnType<typeof setTimeout>>(undefined);

  useEffect(() => {
    return () => clearTimeout(spinnerTimeout.current);
  }, []);

  const submit = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setIsPending(true);
    spinnerTimeout.current = setTimeout(() => setShowSpinner(true), 600);
    props.onSave(selected, {
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
  };

  return (
    <Modal
      size={ModalSize.MEDIUM}
      title={t(`${PREFIX}.modal.title`)}
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
            form="extended-admin-form"
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
          <Trans
            i18nKey={`${PREFIX}.modal.description`}
            values={{ service_name: props.serviceName }}
            components={{ bold: <strong /> }}
          />
        </p>
        <form id="extended-admin-form" onSubmit={submit}>
          <RadioGroup>
            <Radio
              label={t(`${PREFIX}.choices.all.label`)}
              text={t(`${PREFIX}.choices.all.description`, {
                population: DEFAULT_POPULATION_THRESHOLD,
              })}
              name="admin-mode"
              value={ADMIN_MODE_ALL}
              checked={selected === ADMIN_MODE_ALL}
              onChange={() => setSelected(ADMIN_MODE_ALL)}
              fullWidth={true}
            />
            <Radio
              label={t(`${PREFIX}.choices.manual.label`)}
              text={t(`${PREFIX}.choices.manual.description`, {
                population: DEFAULT_POPULATION_THRESHOLD,
              })}
              name="admin-mode"
              value={ADMIN_MODE_MANUAL}
              checked={selected === ADMIN_MODE_MANUAL}
              onChange={() => setSelected(ADMIN_MODE_MANUAL)}
              fullWidth={true}
            />
          </RadioGroup>
        </form>
      </div>
    </Modal>
  );
};
