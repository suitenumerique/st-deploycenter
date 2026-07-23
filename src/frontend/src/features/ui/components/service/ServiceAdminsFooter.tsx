import Link from "next/link";
import { useTranslation } from "react-i18next";

import { Organization, Service } from "@/features/api/Repository";
import { useOperatorContext } from "@/features/layouts/components/GlobalLayout";
import { useServiceAdminCount } from "@/hooks/useQueries";

const PREFIX = "organizations.services.admins";

export const ServiceAdminsFooter = (props: {
  organization: Organization;
  service: Service;
  hideServiceCount?: boolean;
}) => {
  const { t } = useTranslation();
  const { operatorId } = useOperatorContext();
  const { data: adminCount } = useServiceAdminCount(
    operatorId,
    props.organization.id,
    props.service.id,
    !props.hideServiceCount
  );

  const serviceAdminCount = adminCount?.serviceCount ?? 0;
  const globalAdminCount = adminCount?.globalCount ?? 0;
  const showOperatorAdminsNote =
    props.organization.operator_admins_have_admin_role === true;

  const getAccountsUrl = (role: string) =>
    `/operators/${operatorId}/organizations/${props.organization.id}?tab=accounts&role=${encodeURIComponent(role)}`;

  return (
    <div className="dc__service__admins-summary">
      <div>
        {t(`${PREFIX}.label`)} :{" "}
        {!props.hideServiceCount && (
          <>
            <Link
              href={getAccountsUrl(`service.${props.service.id}.admin`)}
              className="dc__service__admins-summary__link"
            >
              {t(`${PREFIX}.service_count`, { count: serviceAdminCount })}
            </Link>
            {" "}{t(`${PREFIX}.and`)}{" "}
          </>
        )}
        <Link
          href={getAccountsUrl("org.admin")}
          className="dc__service__admins-summary__link"
        >
          {t(`${PREFIX}.global_count`, { count: globalAdminCount })}
        </Link>
      </div>
      {showOperatorAdminsNote && (
        <div className="dc__service__admins-summary__note">
          {t(`${PREFIX}.operator_admins_note`)}
        </div>
      )}
    </div>
  );
};
