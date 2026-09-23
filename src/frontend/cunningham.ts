import { cunninghamConfig } from "@gouvfr-lasuite/ui-components";

// The kit exports its themes as `unknown`; the generator only reads the parts
// this file overrides, so name that shape rather than casting at every use.
type Theme = {
  components?: Record<string, unknown>;
  globals?: Record<string, unknown>;
};

const defaultTheme = cunninghamConfig.themes.default as Theme;

// Only two of the switch tokens change, so carry the rest (accent colour, radii,
// handle colours) rather than replacing the whole block.
const defaultSwitch = (defaultTheme.components?.["forms-switch"] ?? {}) as Record<
  string,
  string
>;

const defaultGlobals = (defaultTheme.globals ?? {}) as Record<string, unknown>;
const defaultFont = (defaultGlobals.font ?? {}) as Record<string, unknown>;

// The kit's "default" theme asks for Hanken Grotesk, but globals.scss loads
// Marianne and nothing loads Hanken, so every token consumer fell through to
// bare sans-serif. Marianne is the theme font here, as in the kit's own dsfr
// and anct themes.
const FONT_FAMILY = "Marianne, Inter, Roboto Flex Variable, sans-serif";

// The button "tertiary-text" disabled-colour override that used to live here is
// gone: the kit's buttons now take a semantic colour and a variant, and no
// component token by that name exists to override.
const config = {
  ...cunninghamConfig,
  themes: {
    ...cunninghamConfig.themes,
    default: {
      ...defaultTheme,
      globals: {
        ...defaultGlobals,
        font: {
          ...defaultFont,
          families: { base: FONT_FAMILY, accent: FONT_FAMILY },
        },
      },
      components: {
        ...defaultTheme.components,
        favicon: {
          src: "'/assets/favicon.png'",
        },
        logo: {
          src: "url('/assets/logo_alpha.svg')",
        },
        "logo-icon": {
          src: "url('/assets/logo-icon_alpha.svg')",
        },
        // The kit's off rail is gray-550, which reads as a dark blob on a white
        // card, and the service grids are mostly off. Move it to gray-200 and
        // the disabled rail down to gray-100, which keeps disabled lighter than
        // off, the order the kit ships.
        "forms-switch": {
          ...defaultSwitch,
          "rail-background-color": "#C5C6D5",
          "rail-background-color--disabled": "#E2E2EA",
        },
      },
    },
    anct: {
      components: {
        favicon: {
          src: "'/assets/anct_favicon.png'",
        },
        logo: {
          src: "url('/assets/anct_logo_alpha.svg')",
        },
        "logo-icon": {
          src: "url('/assets/anct_logo-icon.svg')",
        },
      },
    },
  },
};

export default config;
