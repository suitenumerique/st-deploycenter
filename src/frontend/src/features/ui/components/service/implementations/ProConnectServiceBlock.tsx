import {
  MailDomainStatus,
  OperatorIdp,
  Organization,
  Service,
  ServiceSubscription,
} from "@/features/api/Repository";
import { useOperatorContext } from "@/features/layouts/components/GlobalLayout";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import {
  ServiceBlock,
  useServiceBlock,
} from "@/features/ui/components/service/ServiceBlock";
import { Controller, useForm } from "react-hook-form";
import {
  Button,
  Modal,
  ModalSize,
  Select,
  useModal,
} from "@openfun/cunningham-react";
import { ServiceAttribute } from "../ServiceAttribute";
import { Icon, IconSize } from "@gouvfr-lasuite/ui-kit";

/**
 * Handles the ProConnect service block.
 *
 * There are two independents flows:
 *
 * - Activate the subscription
 *   When trying to activate the subscription, we need to validate the data first via canActivateSubscription.
 *   That's why we use a form to validate the data, so it's a future proof solution for future potentially
 *   more complicated validation rules.
 *
 * - Update the IDP
 *   When updating the IDP, we need to save the change to the backend independently
 *   of the form validation. ( Because we setup the IDP before activating the subscription )
 *   It's not possible to update the IDP after activating the subscription.
 */
export const ProConnectServiceBlock = (props: {
  service: Service;
  organization: Organization;
}) => {
  const { t } = useTranslation();
  const { operator } = useOperatorContext();
  const getIdp = (idp_id: string) => {
    return operator?.config.idps?.find((idp) => idp.id == idp_id);
  };

  const onSubmit = useMemo(() => {
    return () => void 0;
  }, []);

  const blockProps = useServiceBlock(props.service, props.organization);

  const {
    handleSubmit,
    control,
    formState: { errors },
  } = useForm({
    defaultValues: {
      mail_domain: props.organization.mail_domain,
      idp_id: props.service.subscription?.metadata?.idp_id,
    },
  });

  const saveIdpChange = (idp?: OperatorIdp) => {
    const data: Partial<ServiceSubscription> = {
      metadata: { idp_id: idp?.id },
    };
    if (!props.service.subscription) {
      data.is_active = false;
    }
    blockProps.onChangeSubscription(data);
  };

  const idpModal = useModal();

  // Check if subscription is less than 48 hours old
  const isSubscriptionLessThan48Hours = useMemo(() => {
    if (!props.service.subscription?.created_at) {
      return false;
    }
    const createdAt = new Date(props.service.subscription.created_at);
    const now = new Date();
    const diffInHours = (now.getTime() - createdAt.getTime()) / (1000 * 60 * 60);
    return diffInHours < 48;
  }, [props.service.subscription?.created_at]);

  return (
    <ServiceBlock
      {...blockProps}
      showGoto={false}
      canActivateSubscription={async () => {
        return new Promise((resolve) => {
          handleSubmit(
            () => resolve(true),
            () => resolve(false)
          )();
        });
      }}
      content={
        <>
          <form onSubmit={handleSubmit(onSubmit)}>
            <div className="dc__service__attribute__container">

              {isSubscriptionLessThan48Hours && props.service.subscription?.is_active && (
                <div className="dc__service__info">
                  <Icon name="info" size={IconSize.SMALL} />
                  {t("organizations.services.proconnect.activation_delay")}
                </div>
              )}

              <Controller
                control={control}
                name="idp_id"
                rules={{ required: true }}
                render={({ field: { value, onChange } }) => (
                  <>
                    <Modal
                      size={ModalSize.SMALL}
                      title={t("organizations.services.idp.modal.title")}
                      closeOnEsc={true}
                      closeOnClickOutside={true}
                      {...idpModal}
                      rightActions={
                        <>
                          <Button type="submit" onClick={idpModal.close}>
                            {t("organizations.services.idp.modal.close")}
                          </Button>
                        </>
                      }
                    >
                      <div className="dc__service__attribute__modal__content">
                        <p className="dc__service__attribute__modal__content__help">
                          {t("organizations.services.idp.modal.help")}
                        </p>
                        <Select
                          label={t("organizations.services.idp.modal.label")}
                          value={value}
                          onChange={(e) => {
                            const idp = getIdp(e.target.value as string);
                            onChange(idp?.id || "");
                            saveIdpChange(idp);
                          }}
                          options={
                            operator?.config.idps?.map((idp) => ({
                              label: idp.name,
                              value: idp.id,
                            })) ?? []
                          }
                        />
                      </div>
                    </Modal>
                    <ServiceAttribute
                      name={t("organizations.services.idp.label")}
                      interactive={!props.service.subscription?.is_active}
                      onClick={() => idpModal.open()}
                      value={
                        getIdp(value)?.name ??
                        t("organizations.services.idp.none")
                      }
                    >
                      {errors.idp_id?.type === "required" && (
                        <p
                          role="alert"
                          className="dc__service__attribute__error"
                        >
                          {t("organizations.services.idp.required")}
                        </p>
                      )}
                    </ServiceAttribute>
                  </>
                )}
              />

              <Controller
                control={control}
                name="mail_domain"
                rules={{ required: true }}
                render={() => (
                  <ServiceAttribute
                    name={t("organizations.services.mail_domain.label")}
                    value={
                      props.organization.mail_domain ??
                      t("organizations.services.mail_domain.none")
                    }
                  >
                    {errors.mail_domain?.type === "required" && (
                      <p role="alert" className="dc__service__attribute__error">
                        {t("organizations.services.mail_domain.required")}
                      </p>
                    )}
                  </ServiceAttribute>
                )}
              />
            </div>
            {props.organization.mail_domain_status ===
              MailDomainStatus.NEED_EMAIL_SETUP && (
              <div className="dc__service__warning">
                {t("organizations.services.mail_domain.need_email_setup")}
              </div>
            )}
            {props.organization.mail_domain_status ===
              MailDomainStatus.INVALID && (
              <div className="dc__service__warning">
                {t("organizations.services.mail_domain.invalid")}
              </div>
            )}
          </form>
          {props.service.config?.help_center_url && (
            <div className="dc__service__block__goto">
              <a target="_blank" href={props.service.config?.help_center_url}>
                {t("organizations.services.help_center.label")}
              </a>
              <Button
                color="tertiary"
                size="nano"
                href={props.service.config?.help_center_url}
                target="_blank"
                icon={<Icon name="open_in_new" size={IconSize.X_SMALL} />}
              ></Button>
            </div>
          )}
        </>
      }
    />
  );
};
