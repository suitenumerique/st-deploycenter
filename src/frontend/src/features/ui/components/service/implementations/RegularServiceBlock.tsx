import { Organization, Service } from "@/features/api/Repository";
import {
    ServiceBlock,
    useServiceBlock,
  } from "@/features/ui/components/service/ServiceBlock";

export const RegularServiceBlock = (props: {
    service: Service;
    organization: Organization;
  }) => {
    const blockProps = useServiceBlock(props.service, props.organization);
    return <ServiceBlock {...blockProps} />;
  };
  