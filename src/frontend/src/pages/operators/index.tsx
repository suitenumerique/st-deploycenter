import { getOperators, Operator } from "@/features/api/Repository";
import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { useRouter } from "next/router";
import { Container } from "@/features/layouts/components/container/Container";
import { getGlobalExplorerLayout } from "@/features/layouts/components/GlobalLayout";
import { useTranslation } from "react-i18next";
import { SpinnerPage } from "@/features/ui/components/spinner/SpinnerPage";

const OperatorCard = ({ operator }: { operator: Operator }) => {
  const router = useRouter();
  return (
    <button
      className="dc__operator-card"
      onClick={() => router.push(`/operators/${operator.id}`)}
    >
      <span className="dc__operator-card__name">{operator.name}</span>
      {operator.url && (
        <span className="dc__operator-card__url">{operator.url}</span>
      )}
    </button>
  );
};

export default function Operators() {
  const { data, isLoading } = useQuery({
    queryKey: ["operators"],
    refetchOnWindowFocus: false,
    refetchOnMount: false,
    queryFn: getOperators,
  });
  const router = useRouter();
  const { t } = useTranslation();

  useEffect(() => {
    if (!data) {
      return;
    }
    if (data.count === 1) {
      router.push(`/operators/${data.results[0].id}`);
    }
  }, [data]);

  if (isLoading || data?.count === 1) {
    return <SpinnerPage />;
  }

  return (
    <Container title={t("operators.title")} subtitle={t("operators.subtitle")}>
      <div className="dc__operators__list">
        {data?.results.map((operator) => (
          <OperatorCard key={operator.id} operator={operator} />
        ))}
      </div>
    </Container>
  );
}

Operators.getLayout = getGlobalExplorerLayout;
