import { ThemeCustomization } from "@/features/api/types";
import { splitLocaleCode } from "@/features/i18n/utils";
import { useTranslation } from "react-i18next";
import theme_config from "./default.json";

export const useThemeCustomization = (key: keyof ThemeCustomization) => {
  
  const { i18n } = useTranslation();
  const language = splitLocaleCode(i18n.language).language;
  const themeCustomization = theme_config[key];
  return {
    ...themeCustomization?.default,
    ...(themeCustomization?.[language as keyof typeof themeCustomization] ??
      {}),
  };
};
