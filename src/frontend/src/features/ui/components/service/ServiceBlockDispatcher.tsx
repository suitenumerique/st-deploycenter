import {
  Organization,
  Service,
  SERVICE_TYPE_PROCONNECT,
} from "@/features/api/Repository";
import { ProConnectServiceBlock } from "@/features/ui/components/service/implementations/ProConnectServiceBlock";
import { RegularServiceBlock } from "@/features/ui/components/service/implementations/RegularServiceBlock";

export const ServiceBlockDispatcher = (props: {
  service: Service;
  organization: Organization;
}) => {
  if (props.service.type === SERVICE_TYPE_PROCONNECT) {
    return <ProConnectServiceBlock {...props} />;
  }
  return <RegularServiceBlock {...props} />;
};
