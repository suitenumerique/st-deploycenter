import { Query, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MutationCache } from "@tanstack/react-query";
import { QueryCache } from "@tanstack/react-query";
import { NextPage } from "next";
import type { AppProps } from "next/app";
import { ReactElement, ReactNode } from "react";
import { CunninghamProvider } from "@gouvfr-lasuite/ui-kit";
import { APIError, errorToString } from "@/features/api/APIError";
import {
  addToast,
  ToasterItem,
} from "@/features/ui/components/toaster/Toaster";
import { capitalizeRegion } from "@/features/i18n/utils";
import Head from "next/head";
import { useTranslation } from "react-i18next";
import "@/styles/globals.scss";
import "@/features/i18n/initI18n";

export type NextPageWithLayout<P = object, IP = P> = NextPage<P, IP> & {
  getLayout?: (page: ReactElement) => ReactNode;
};

type AppPropsWithLayout = AppProps & {
  Component: NextPageWithLayout;
};

const onError = (error: Error, query: unknown) => {
  if ((query as Query).meta?.noGlobalError) {
    return;
  }

  // Don't show toast for 401/403 errors because the app handles them by
  // redirecting to the 401/403 page. So we don't want to show a toast before
  // the redirect, it would feels buggy.
  if (error instanceof APIError && (error.code === 401 || error.code === 403)) {
    return;
  }

  addToast(
    <ToasterItem type="error">
      <span>{errorToString(error)}</span>
    </ToasterItem>
  );
};

const queryClient = new QueryClient({
  mutationCache: new MutationCache({
    onError: (error, variables, context, mutation) => {
      onError(error, mutation);
    },
  }),
  queryCache: new QueryCache({
    onError: (error, query) => onError(error, query),
  }),
  defaultOptions: {
    queries: {
      retry: false,
    },
  },
});

export default function App({ Component, pageProps }: AppPropsWithLayout) {
  const getLayout = Component.getLayout ?? ((page) => page);
  const { t, i18n } = useTranslation();
  // const { theme } = useAppContext();
  // const themeTokens = useCunninghamTheme();
  return (
    <>
      <Head>
        <title>{t("app_title")}</title>
      </Head>
      <QueryClientProvider client={queryClient}>
        <CunninghamProvider
          currentLocale={capitalizeRegion(i18n.language)}
          theme={"default"}
        >
          {/* <ConfigProvider> */}
          {/* <AnalyticsProvider> */}
          {getLayout(<Component {...pageProps} />)}

          {/* </AnalyticsProvider> */}
          {/* </ConfigProvider> */}
        </CunninghamProvider>
      </QueryClientProvider>
    </>
  );
}
