import { Spinner } from "@gouvfr-lasuite/ui-kit";
import { useTranslation } from "react-i18next";
import { useRouter } from "next/router";
import { Operator } from "@/features/api/Repository";

export const useBreadcrumbOperator = (
  operatorId: string,
  operator?: Operator,
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
        {t("organizations.title", { operator: operator?.name })}
        {isOperatorLoading && <Spinner />}
      </button>
    ),
  };
};
