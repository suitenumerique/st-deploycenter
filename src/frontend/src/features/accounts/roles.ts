/**
 * Centralized role definitions for accounts.
 * Roles are defined per service type, similar to how service cards work.
 */

export type RoleDefinition = {
  value: string;
  labelKey: string; // i18n key
};

/**
 * Global roles that apply at the organization level
 */
export const GLOBAL_ROLES: RoleDefinition[] = [
  { value: "admin", labelKey: "accounts.roles.admin" },
];

/**
 * Service-specific roles, keyed by service type
 */
export const SERVICE_ROLES: Record<string, RoleDefinition[]> = {
  proconnect: [],
  drive: [],
  rdvsp: [
    { value: "admin", labelKey: "accounts.roles.admin" },
    
  ],
  default: [],
};

/**
 * Get roles for a specific service type
 */
export const getServiceRoles = (serviceType: string): RoleDefinition[] => {
  return SERVICE_ROLES[serviceType] || SERVICE_ROLES.default;
};

