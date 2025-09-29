import { FooterProps } from "@gouvfr-lasuite/ui-kit";

export type LocalizedThemeCustomization<T> = {
    default: T;
    [key: string]: T;
  };
  
  export interface ThemeCustomization {
    footer?: LocalizedThemeCustomization<FooterProps>;
  }