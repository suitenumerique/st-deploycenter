import { getOperators } from "@/features/api/Repository";
import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { useRouter } from "next/router";
import { Container } from "@/features/layouts/components/container/Container";
import { getGlobalExplorerLayout } from "@/features/layouts/components/GlobalLayout";
import { useTranslation } from "react-i18next";
import { SpinnerPage } from "@/features/ui/components/spinner/SpinnerPage";
import { Button } from "@openfun/cunningham-react";

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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data]);

  if (isLoading || data?.count === 1) {
    return <SpinnerPage />;
  }

  return (
    <Container title={t("operators.title")} subtitle={t("operators.subtitle")}>
      <div className="dc__operators__list">
        {data?.results.map((operator) => (
          <Button
            key={operator.id}
            onClick={() => router.push(`/operators/${operator.id}`)}
          >
            {operator.name}
          </Button>
        ))}
      </div>
    </Container>
  );
}

Operators.getLayout = getGlobalExplorerLayout;
