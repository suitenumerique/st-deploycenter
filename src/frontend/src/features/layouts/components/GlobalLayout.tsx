import { Auth } from "@/features/auth/Auth";
import { MainLayout } from "@gouvfr-lasuite/ui-kit";
import { HeaderRight } from "./header/Header";
import { HeaderIcon } from "./header/Header";
import { LeftPanelMobile } from "./left-panel/LeftPanelMobile";

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
      <MainLayout
        hideLeftPanelOnDesktop={true}
        leftPanelContent={<LeftPanelMobile />}
        enableResize
        icon={<HeaderIcon />}
        rightHeaderContent={<HeaderRight />}
      >
        {children}
      </MainLayout>
    </GlobalLayout>
  );
};
