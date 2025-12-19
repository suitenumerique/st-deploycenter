import {
  Button,
  Input,
  Modal,
  ModalProps,
  ModalSize,
  Select,
  useModal,
} from "@openfun/cunningham-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { ServiceAttribute } from "@/features/ui/components/service/ServiceAttribute";
import { useMutationUpdateEntitlement } from "@/hooks/useQueries";
import { useOperatorContext } from "@/features/layouts/components/GlobalLayout";
import { Spinner } from "@gouvfr-lasuite/ui-kit";
import { Entitlement } from "@/features/api/Repository";
import { ServiceBlockEntitlementFieldProps } from "@/features/ui/components/service/entitlements/ServiceBlockEntitlements";

const DECIMALS = 2;
// Order matters ! The biggest unit should be first.
const UNITS = {
  TB: 1000 * 1000 * 1000 * 1000,
  GB: 1000 * 1000 * 1000,
  MB: 1000 * 1000,
};

/**
 * Gets the value and unit from a number of bytes.
 * The number is formatted with the correct number of decimals.
 * The unit is the biggest unit possible if the number is greater than 1, otherwise the smallest unit.
 */
const fromBytes = (bytes: number) => {
  let out: [number, string] | undefined = undefined;
  for (const unit in UNITS) {
    const multiplier = UNITS[unit as keyof typeof UNITS];
    if (bytes / multiplier >= 1) {
      out = [bytes / multiplier, unit];
      break;
    }
  }
  if (!out) {
    // If no unit is found, use the last unit.
    const lastUnit = Object.keys(UNITS)[Object.keys(UNITS).length - 1];
    const lastUnitMultiplier = UNITS[lastUnit as keyof typeof UNITS];
    out = [bytes / lastUnitMultiplier, lastUnit];
  }

  // Format the number with the correct number of decimals.
  out[0] = parseFloat(out[0].toFixed(DECIMALS));
  return out;
};

/**
 * Gets the number of bytes from a value and unit.
 */
const toBytes = (value: number, unit: string) => {
  const multiplier = UNITS[unit as keyof typeof UNITS];
  return value * multiplier;
};

/**
 * Gets the translation prefix for an entitlement field.
 */
const getTranslationPrefix = (
  serviceType: string,
  entitlement: Entitlement,
  fieldName: string,
  priority: string
) => {
  return `organizations.services.types.${serviceType}.entitlements.${entitlement.type}.${fieldName}.${entitlement.account_type}`;
};

export const StoragePickerEntitlementField = (
  props: ServiceBlockEntitlementFieldProps
) => {
  const { t } = useTranslation();
  const [value, unit] = useMemo(
    () =>
      fromBytes(parseInt(props.entitlement?.config.max_storage as string) || 0),
    [props.entitlement?.config.max_storage]
  );

  const modal = useModal({
    isOpenDefault: false,
  });
  const translationPrefix = getTranslationPrefix(
    props.service.type,
    props.entitlement,
    props.fieldName,
    props.priority
  );
  return (
    <>
      {/* The goal is reset the modal state when the component is unmounted */}
      {modal.isOpen && (
        <StoragePickerEntitlementFieldModal {...modal} {...props} />
      )}
      <ServiceAttribute
        name={t(`${translationPrefix}.label`)}
        value={
          value ? `${value} ${unit}` : t(`${translationPrefix}.zero_value`)
        }
        onClick={() => modal.open()}
        interactive={true}
      />
    </>
  );
};

const StoragePickerEntitlementFieldModal = (
  props: ServiceBlockEntitlementFieldProps &
    Pick<ModalProps, "isOpen" | "onClose">
) => {
  const translationPrefix = getTranslationPrefix(
    props.service.type,
    props.entitlement,
    props.fieldName,
    props.priority
  );
  const { t } = useTranslation();

  const [initialValue, initialUnit] = fromBytes(
    parseInt(props.entitlement?.config.max_storage as string) || 0
  );

  const { operatorId } = useOperatorContext();
  const { mutate: updateEntitlement } = useMutationUpdateEntitlement();

  const [value, setValue] = useState(initialValue);
  const [unit, setUnit] = useState(initialUnit);
  const [isLoading, setIsLoading] = useState(false);

  const submit = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setIsLoading(true);

    updateEntitlement(
      {
        operatorId,
        organizationId: props.organization.id,
        serviceId: props.service.id,
        entitlementId: props.entitlement.id,
        data: {
          config: { max_storage: toBytes(value, unit) },
        },
      },
      {
        onSuccess: () => {
          setIsLoading(false);
          props.onClose();
        },
        onError: () => {
          setIsLoading(false);
        },
      }
    );
  };

  return (
    <Modal
      size={ModalSize.SMALL}
      title={t(`${translationPrefix}.modal.title`)}
      closeOnEsc={true}
      closeOnClickOutside={true}
      rightActions={
        <>
          <Button
            type="button"
            onClick={props.onClose}
            color="secondary"
            disabled={isLoading}
          >
            {t("common.cancel")}
          </Button>
          <Button
            type="submit"
            form="storage-picker-form"
            disabled={isLoading}
            icon={isLoading ? <Spinner /> : undefined}
            iconPosition="right"
          >
            {t("common.save")}
          </Button>
        </>
      }
      {...props}
    >
      <div className="dc__service__attribute__modal__content">
        <p className="dc__service__attribute__modal__content__help">
          {t(`${translationPrefix}.modal.description`)}
        </p>

        <form
          id="storage-picker-form"
          onSubmit={submit}
          className="dc__service__attribute__modal__content__storage-picker__inputs"
        >
          <Input
            label={t(
              `organizations.services.entitlements.fields.storage_picker.input_placeholder`
            )}
            type="number"
            min="0"
            step="0.01"
            value={value}
            onChange={(e) => setValue(parseFloat(e.target.value))}
          />
          <Select
            label={t(
              `organizations.services.entitlements.fields.storage_picker.unit_placeholder`
            )}
            value={unit}
            clearable={false}
            onChange={(e) => setUnit(e.target.value as string)}
            options={Object.keys(UNITS).map((unit) => ({
              label: unit,
              value: unit,
            }))}
          />
        </form>
      </div>
    </Modal>
  );
};
