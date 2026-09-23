import {
  Button,
  Modal,
  ModalSize,
  Radio,
  RadioGroup,
} from "@gouvfr-lasuite/ui-components";
import { Spinner } from "@gouvfr-lasuite/ui-components";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { MutateOptions } from "@tanstack/react-query";

export type Choice = {
  value: string;
  label: string;
  description: string;
};

// Modal picking one value among radio choices, saved on submit.
export const ChoiceModal = (props: {
  isOpen: boolean;
  onClose: () => void;
  title: string;
  description: React.ReactNode;
  name: string;
  choices: Choice[];
  value: string;
  onSave: (
    value: string,
    options?: MutateOptions<unknown, unknown, unknown, unknown>
  ) => void;
}) => {
  const { t } = useTranslation();
  const [selected, setSelected] = useState(props.value);
  const [isPending, setIsPending] = useState(false);
  const [showSpinner, setShowSpinner] = useState(false);
  const spinnerTimeout = useRef<ReturnType<typeof setTimeout>>(undefined);
  const formId = `${props.name}-form`;

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
      title={props.title}
      closeOnEsc={!isPending}
      closeOnClickOutside={!isPending}
      isOpen={props.isOpen}
      onClose={props.onClose}
      rightActions={
        <>
          <Button
            type="button"
            onClick={props.onClose}
            variant="secondary"
            disabled={isPending}
          >
            {t("common.cancel")}
          </Button>
          <Button
            type="submit"
            form={formId}
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
          {props.description}
        </p>
        <form id={formId} onSubmit={submit}>
          <RadioGroup>
            {props.choices.map((choice) => (
              <Radio
                key={choice.value}
                label={choice.label}
                text={choice.description}
                name={props.name}
                value={choice.value}
                checked={selected === choice.value}
                onChange={() => setSelected(choice.value)}
                fullWidth={true}
              />
            ))}
          </RadioGroup>
        </form>
      </div>
    </Modal>
  );
};
