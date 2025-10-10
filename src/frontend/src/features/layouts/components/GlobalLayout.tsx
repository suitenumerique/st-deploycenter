import { Auth } from "@/features/auth/Auth";
import { MainLayout } from "@gouvfr-lasuite/ui-kit";
import { HeaderRight } from "./header/Header";
import { HeaderIcon } from "./header/Header";
import { LeftPanelMobile } from "./left-panel/LeftPanelMobile";
import { Toaster } from "@/features/ui/components/toaster/Toaster";
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
  return (
    <GlobalLayout>
      <OperatorContextProvider>
        <MainLayout
          hideLeftPanelOnDesktop={true}
          leftPanelContent={<LeftPanelMobile />}
          enableResize
          icon={<HeaderIcon />}
          rightHeaderContent={<HeaderRight />}
        >
          {children}
          <Toaster />
        </MainLayout>
      </OperatorContextProvider>
    </GlobalLayout>
  );
};

export const OperatorContext = createContext<{
  operator?: Operator | null;
  operatorQuery: UseQueryResult<Operator, Error>;
}>({
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
      value={{ operator: operatorQuery.data ?? null, operatorQuery }}
    >
      {children}
    </OperatorContext.Provider>
  );
};
