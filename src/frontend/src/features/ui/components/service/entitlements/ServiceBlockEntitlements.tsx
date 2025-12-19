import { Entitlement } from "@/features/api/Repository";
import {
  EntitlementFields,
  ServiceBlockProps,
} from "@/features/ui/components/service/ServiceBlock";
import { StoragePickerEntitlementField } from "@/features/ui/components/service/entitlements/fields/StoragePickerEntitlementField";

const getEntitlementsByPriority = (entitlements: Entitlement[]) => {
  const accountOverride = entitlements?.find(
    (e) => e.account_type !== "organization" && !!e.account_type && e.account_id
  );
  const account = entitlements?.find(
    (e) =>
      e.account_type !== "organization" && !!e.account_type && !e.account_id
  );
  const organization = entitlements?.find(
    (e) => e.account_type === "organization" && !e.account_id
  );
  return {
    accountOverride,
    account,
    organization,
  };
};

export const ServiceBlockEntitlements = (props: ServiceBlockProps) => {
  return (
    <div className="dc__service__block__entitlements">
      {Object.entries(props.entitlementsFields).map(
        ([entitlementType, entitlementFields]) => {
          const entitlements = props.service.subscription?.entitlements?.filter(
            (e) => e.type === entitlementType
          );
          const entitlementsByPriority =
            getEntitlementsByPriority(entitlements);
          return Object.entries(entitlementsByPriority).map(
            ([priority, entitlement]) => {
              if (!entitlement) {
                return null;
              }
              return (
                <ServiceBlockEntitlement
                  key={entitlement.id}
                  priority={priority}
                  entitlement={entitlement}
                  entitlementFields={entitlementFields}
                  {...props}
                />
              );
            }
          );
        }
      )}
    </div>
  );
};

type ServiceBlockEntitlementProps = {
  priority: string;
  entitlementType?: string;
  entitlementFields: EntitlementFields;
  entitlement: Entitlement;
} & ServiceBlockProps;

const ServiceBlockEntitlement = (props: ServiceBlockEntitlementProps) => {
  return (
    <div className="dc__service__block__entitlement">
      <div className="dc__service__block__entitlement__fields">
        {Object.entries(props.entitlementFields.fields).map(
          ([fieldName, field]) => {
            return (
              <ServiceBlockEntitlementField
                key={fieldName}
                fieldName={fieldName}
                field={field}
                {...props}
              />
            );
          }
        )}
      </div>
    </div>
  );
};

export type ServiceBlockEntitlementFieldProps = {
  fieldName: string;
  field: { type: string };
  entitlement: Entitlement;
} & ServiceBlockEntitlementProps;

const ServiceBlockEntitlementField = (
  props: ServiceBlockEntitlementFieldProps
) => {
  switch (props.field.type) {
    case "storage_picker":
      return <StoragePickerEntitlementField {...props} />;
    default:
      return <div>Unknown field type: {props.field.type}</div>;
  }
};
