import { Spinner } from "@gouvfr-lasuite/ui-kit";
import { useTranslation } from "react-i18next";
import { useRouter } from "next/router";
import { Operator } from "@/features/api/Repository";

export const useBreadcrumbOperator = (
  operatorId: string,
  operator?: Operator | null,
  isOperatorLoading?: boolean
) => {
  const { t } = useTranslation();
  const router = useRouter();
  return {
    content: (
      <button
        className="c__breadcrumbs__button"
        data-testid="breadcrumb-button"
        onClick={() => router.push(`/operators/${operatorId}`)}
      >
        <img src="/assets/icons/organization.svg" alt="Logo" />
        {t("organizations.title")}
        {isOperatorLoading && <Spinner />}
      </button>
    ),
  };
};
