import {
  Organization,
  OtherOperatorSubscription,
  Service,
} from "@/features/api/Repository";
import {
  ServiceBlock,
  useServiceBlock,
} from "@/features/ui/components/service/ServiceBlock";

export const RegularServiceBlock = (props: {
  service: Service;
  organization: Organization;
  isManagedByOtherOperator?: boolean;
  managingOperatorSubscription?: OtherOperatorSubscription;
}) => {
  const blockProps = useServiceBlock(props.service, props.organization);
  return (
    <ServiceBlock
      {...blockProps}
      isManagedByOtherOperator={props.isManagedByOtherOperator}
      managingOperatorSubscription={props.managingOperatorSubscription}
    />
  );
};
  