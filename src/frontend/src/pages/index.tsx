import Head from "next/head";
import { GlobalLayout } from "@/features/layouts/components/GlobalLayout";
import { login, useAuth } from "@/features/auth/Auth";
import {
  Footer,
  Hero,
  HomeGutter,
  Icon,
  IconType,
  MainLayout,
  ProConnectButton,
} from "@gouvfr-lasuite/ui-kit";
import { Button } from "@openfun/cunningham-react";
import { useTranslation } from "react-i18next";
import banner from "@/assets/home/banner.png";
import { LogoutButton } from "@/features/auth/components/LogoutButton";
import { Toaster } from "@/features/ui/components/toaster/Toaster";
import { LeftPanelMobile } from "@/features/layouts/components/left-panel/LeftPanelMobile";
import { HeaderRight } from "@/features/layouts/components/header/Header";
import { useThemeCustomization } from "@/hooks/useThemeCustomization";
import { SpinnerPage } from "@/features/ui/components/spinner/SpinnerPage";
import { useEffect } from "react";
import { useRouter } from "next/router";

export default function Home() {
  const { user } = useAuth();
  const { t } = useTranslation();
  const router = useRouter();
  const footerCustommization = useThemeCustomization("footer");

  useEffect(() => {
    if (user) {
      router.push("/operators");
    }
  }, [user]);

  if (user) {
    return <SpinnerPage />;
  }

  return (
    <>
      <Head>
        <title>{t("app_title")}</title>
        <meta name="description" content={t("app_description")} />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <link rel="icon" href="/favicon.png" />
      </Head>

      <HomeGutter>
        <Hero
          logo={<div className="drive__logo-icon" />}
          banner={banner.src}
          title={t("home.title")}
          subtitle={t("home.subtitle")}
          mainButton={
            <div className="c__hero__buttons">
              <div>
                <ProConnectButton onClick={() => login()} />
              </div>
            </div>
          }
        />
      </HomeGutter>
      <Footer {...footerCustommization} />
    </>
  );
}

Home.getLayout = (page: React.ReactElement) => {
  return (
    <div className="drive__home">
      <GlobalLayout>
        <MainLayout
          enableResize
          hideLeftPanelOnDesktop={true}
          leftPanelContent={<LeftPanelMobile />}
          icon={
            <div className="drive__header__left">
              <img src="/assets/logo-gouv.svg" alt="" />
              <div className="drive__header__logo" />
            </div>
          }
          rightHeaderContent={<HeaderRight />}
        >
          {page}
          <Toaster />
        </MainLayout>
      </GlobalLayout>
    </div>
  );
};
