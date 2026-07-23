import { useRouter } from "next/router";
import { useEffect, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Spinner } from "@gouvfr-lasuite/ui-kit";
import { Container } from "@/features/layouts/components/container/Container";
import {
  getGlobalExplorerLayout,
  useOperatorContext,
} from "@/features/layouts/components/GlobalLayout";
import { Breadcrumbs } from "@/features/ui/components/breadcrumbs/Breadcrumbs";
import { useBreadcrumbOperator } from "@/features/ui/components/breadcrumbs/Parts";
import { useOperatorOrganizations } from "@/hooks/useQueries";

/**
 * Resolver route: /operators/:operator_id/organizations/?siret=XYZ (or ?siren=, ?search=).
 *
 * Looks up the organization by its identifier and redirects to the canonical
 * detail URL /operators/:operator_id/organizations/:id. The backend `search`
 * param matches SIRET and SIREN exactly (SIRET ranked first), so we reuse it.
 */
export default function OrganizationResolver() {
  const router = useRouter();
  const { t } = useTranslation();
  const operatorId = router.query.operator_id as string;

  const {
    operator,
    operatorQuery: { isLoading: isOperatorLoading },
  } = useOperatorContext();
  const breadcrumbOperator = useBreadcrumbOperator(
    operatorId,
    operator,
    isOperatorLoading
  );

  // The identifier to resolve, and the extra query params to forward (e.g. tab).
  const { searchTerm, forwardedQuery } = useMemo(() => {
    if (!router.isReady) {
      return { searchTerm: "", forwardedQuery: {} };
    }
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    const { operator_id: _operatorId, siret, siren, search, ...rest } =
      router.query;
    const first = (v: typeof siret) => (Array.isArray(v) ? v[0] : v) ?? "";
    return {
      searchTerm: (first(siret) || first(siren) || first(search)).trim(),
      forwardedQuery: rest,
    };
  }, [router.isReady, router.query]);

  const { data: organizations, isLoading } = useOperatorOrganizations(
    operatorId,
    { search: searchTerm },
    router.isReady && !!searchTerm
  );

  const match = organizations?.results?.[0];

  useEffect(() => {
    if (!match) {
      return;
    }
    router.replace({
      pathname: `/operators/${operatorId}/organizations/${match.id}`,
      query: forwardedQuery,
    });
  }, [match, operatorId, router, forwardedQuery]);

  const noIdentifier = router.isReady && !searchTerm;
  const notFound =
    !!searchTerm && !isLoading && (organizations?.results?.length ?? 0) === 0;

  return (
    <Container
      titleNode={<Breadcrumbs items={[breadcrumbOperator]} />}
    >
      <div className="dc__organization__resolver">
        {noIdentifier ? (
          <p>{t("organizations.redirect.missing_identifier")}</p>
        ) : notFound ? (
          <p>{t("organizations.redirect.not_found")}</p>
        ) : (
          <p>
            <Spinner /> {t("organizations.redirect.searching")}
          </p>
        )}
      </div>
    </Container>
  );
}

OrganizationResolver.getLayout = getGlobalExplorerLayout;
