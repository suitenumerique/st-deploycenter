import {
  Organization,
  Service,
  SERVICE_TYPE_ADC,
  SERVICE_TYPE_DRIVE,
  SERVICE_TYPE_ESD,
  SERVICE_TYPE_MESSAGES,
  SERVICE_TYPE_PROCONNECT,
} from "@/features/api/Repository";
import { DriveServiceBlock } from "@/features/ui/components/service/implementations/DriveServiceBlock";
import { ExtendedAdminServiceBlock } from "@/features/ui/components/service/implementations/ExtendedAdminServiceBlock";
import { MessagesServiceBlock } from "@/features/ui/components/service/implementations/MessagesServiceBlock";
import { ProConnectServiceBlock } from "@/features/ui/components/service/implementations/ProConnectServiceBlock";
import { RegularServiceBlock } from "@/features/ui/components/service/implementations/RegularServiceBlock";

export type ServiceBlockDispatcherProps = {
  service: Service;
  organization: Organization;
};

export const ServiceBlockDispatcher = (props: ServiceBlockDispatcherProps) => {
  if (props.service.type === SERVICE_TYPE_PROCONNECT) {
    return <ProConnectServiceBlock {...props} />;
  }
  if (props.service.type === SERVICE_TYPE_ADC || props.service.type === SERVICE_TYPE_ESD) {
    return <ExtendedAdminServiceBlock {...props} />;
  }
  if (props.service.type === SERVICE_TYPE_MESSAGES) {
    return <MessagesServiceBlock {...props} />;
  }
  if (props.service.type === SERVICE_TYPE_DRIVE) {
    return <DriveServiceBlock {...props} />;
  }
  return <RegularServiceBlock {...props} />;
};
