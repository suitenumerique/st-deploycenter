import { Auth } from "@/features/auth/Auth";
import { MainLayout } from "@gouvfr-lasuite/ui-components";
import { HeaderRight } from "./header/Header";
import { HeaderIcon } from "./header/Header";
import { LeftPanel } from "./left-panel/LeftPanel";
import { Toaster } from "@/features/ui/components/toaster/Toaster";
import { FeedbackWidget } from "@/features/ui/components/feedback-widget";
import { createContext, useContext } from "react";
import { Operator } from "@/features/api/Repository";
import { UseQueryResult } from "@tanstack/react-query";
import { useRouter } from "next/router";
import useOperator from "@/hooks/useQueries";

/**
 * This layout is used for the global contexts (auth, etc).
 */
export const GlobalLayout = ({ children }: { children: React.ReactNode }) => {
  return <Auth>{children}</Auth>;
};

export const getGlobalExplorerLayout = (page: React.ReactElement) => {
  return <GlobalExplorerLayout>{page}</GlobalExplorerLayout>;
};

export const GlobalExplorerLayout = ({
  children,
}: {
  children: React.ReactNode;
}) => {
  const router = useRouter();
  // The panel only holds operator-scoped navigation, so on the operator picker
  // it would be an empty column. Read it off the route pattern and not off
  // query.operator_id, which is undefined until the router is ready and would
  // shift the layout after hydration.
  const isOperatorScoped = router.pathname.startsWith("/operators/[operator_id]");

  return (
    <GlobalLayout>
      <OperatorContextProvider>
        {/* hideLeftPanelOnDesktop only covers desktop: the kit always renders
            the mobile drawer and its burger. The class hides those two, and
            display:contents keeps the wrapper out of the layout. */}
        <div className={isOperatorScoped ? undefined : "dc__no-left-panel"}>
          <MainLayout
            leftPanelContent={<LeftPanel />}
            hideLeftPanelOnDesktop={!isOperatorScoped}
            enableResize
            icon={<HeaderIcon />}
            rightHeaderContent={<HeaderRight />}
          >
            {children}
            <Toaster />
            <FeedbackWidget />
          </MainLayout>
        </div>
      </OperatorContextProvider>
    </GlobalLayout>
  );
};

export const OperatorContext = createContext<{
  operatorId: string;
  operator?: Operator | null;
  operatorQuery: UseQueryResult<Operator, Error>;
}>({
  operatorId: "",
  operator: null,
  operatorQuery: undefined as unknown as UseQueryResult<Operator, Error>,
});

export const useOperatorContext = () => {
  const context = useContext(OperatorContext);
  if (!context) {
    throw new Error("useOperatorContext must be used within a OperatorContext");
  }
  return context;
};

const OperatorContextProvider = ({
  children,
}: {
  children: React.ReactNode;
}) => {
  const router = useRouter();
  const operatorId = router.query.operator_id as string;
  const operatorQuery = useOperator(operatorId);
  return (
    <OperatorContext.Provider
      value={{
        operatorId,
        operator: operatorQuery.data ?? null,
        operatorQuery,
      }}
    >
      {children}
    </OperatorContext.Provider>
  );
};
