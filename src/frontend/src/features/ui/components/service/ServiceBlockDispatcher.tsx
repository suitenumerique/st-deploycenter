import {
  Organization,
  OtherOperatorSubscription,
  Service,
  SERVICE_TYPE_ADC,
  SERVICE_TYPE_ESD,
  SERVICE_TYPE_PROCONNECT,
} from "@/features/api/Repository";
import { ExtendedAdminServiceBlock } from "@/features/ui/components/service/implementations/ExtendedAdminServiceBlock";
import { ProConnectServiceBlock } from "@/features/ui/components/service/implementations/ProConnectServiceBlock";
import { RegularServiceBlock } from "@/features/ui/components/service/implementations/RegularServiceBlock";

export type ServiceBlockDispatcherProps = {
  service: Service;
  organization: Organization;
  isManagedByOtherOperator?: boolean;
  managingOperatorSubscription?: OtherOperatorSubscription;
};

export const ServiceBlockDispatcher = (props: {
  service: Service;
  organization: Organization;
}) => {
  const otherSub = props.service.other_operator_subscription;

  // Service is "managed by other operator" if another operator has a subscription
  // AND the current operator doesn't have their own subscription
  const isManagedByOtherOperator = !!otherSub && !props.service.subscription;

  const dispatcherProps: ServiceBlockDispatcherProps = {
    ...props,
    isManagedByOtherOperator,
    managingOperatorSubscription: otherSub ?? undefined,
  };

  if (props.service.type === SERVICE_TYPE_PROCONNECT) {
    return <ProConnectServiceBlock {...dispatcherProps} />;
  }
  if (props.service.type === SERVICE_TYPE_ADC || props.service.type === SERVICE_TYPE_ESD) {
    return <ExtendedAdminServiceBlock {...dispatcherProps} />;
  }
  return <RegularServiceBlock {...dispatcherProps} />;
};
