import { Entitlement, EntitlementDefault } from "@/features/api/Repository";
import {
  EntitlementFields,
  ServiceBlockProps,
} from "@/features/ui/components/service/ServiceBlock";
import { StoragePickerEntitlementField } from "@/features/ui/components/service/entitlements/fields/StoragePickerEntitlementField";

/**
 * Get entitlements to display, using defaults if no subscription exists yet.
 * Returns entitlements grouped by priority (organization, account, accountOverride).
 */
const getEntitlementsByPriority = (
  entitlements: Entitlement[] | undefined,
  entitlementType: string,
  entitlementDefaults: EntitlementDefault[] | undefined
): Record<string, Entitlement | null> => {
  // If we have real entitlements, use them
  if (entitlements && entitlements.length > 0) {
    const accountOverride = entitlements.find(
      (e) => e.account_type !== "organization" && !!e.account_type && e.account_id
    );
    const account = entitlements.find(
      (e) =>
        e.account_type !== "organization" && !!e.account_type && !e.account_id
    );
    const organization = entitlements.find(
      (e) => e.account_type === "organization" && !e.account_id
    );

    return {
      accountOverride: accountOverride || null,
      account: account || null,
      organization: organization || null,
    };
  }

  // No subscription yet - show defaults from service config
  const result: Record<string, Entitlement | null> = {
    accountOverride: null,
    account: null,
    organization: null,
  };

  if (entitlementDefaults) {
    for (const defaultEnt of entitlementDefaults) {
      if (defaultEnt.type !== entitlementType) continue;

      const isOrg = defaultEnt.account_type === "organization";
      const key = isOrg ? "organization" : "account";

      result[key] = {
        id: "",
        type: defaultEnt.type,
        account_type: defaultEnt.account_type,
        account_id: "",
        config: { ...defaultEnt.config },
      };
    }
  }

  return result;
};

export const ServiceBlockEntitlements = (props: ServiceBlockProps) => {
  // Only show entitlements if showEntitlementsBeforeSubscription is enabled
  // or if we have a subscription
  const hasSubscription = !!props.service.subscription;
  const showEntitlements =
    hasSubscription || props.showEntitlementsBeforeSubscription;

  if (!showEntitlements) {
    return null;
  }

  return (
    <div className="dc__service__block__entitlements">
      {Object.entries(props.entitlementsFields).map(
        ([entitlementType, entitlementFields]) => {
          const entitlements = props.service.subscription?.entitlements?.filter(
            (e) => e.type === entitlementType
          );
          const entitlementsByPriority = getEntitlementsByPriority(
            entitlements,
            entitlementType,
            props.service.entitlement_defaults
          );
          return Object.entries(entitlementsByPriority).map(
            ([priority, entitlement]) => {
              if (!entitlement) {
                return null;
              }
              return (
                <ServiceBlockEntitlement
                  key={entitlement.id || `${entitlementType}-${priority}`}
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
