// eslint-config-next 16 ships native flat config, so the @eslint/eslintrc
// FlatCompat shim this file used to go through is gone: running the v16 config
// through it throws "Converting circular structure to JSON".
import coreWebVitals from "eslint-config-next/core-web-vitals";
import typescript from "eslint-config-next/typescript";

const eslintConfig = [
  ...coreWebVitals,
  ...typescript,
  {
    rules: {
      "react-hooks/exhaustive-deps": "off",
      "@next/next/no-img-element": "off",
      // Turned on by eslint-config-next 16 and flags 11 existing effects across
      // 8 components (auth, the service and account modals, the query hooks,
      // the metrics page). Rewriting them is a React change, not a dependency
      // bump, so it is deliberately deferred rather than done here.
      "react-hooks/set-state-in-effect": "off",
    },
  },
  {
    ignores: [
      "node_modules/**",
      ".next/**",
      "out/**",
      "build/**",
      "next-env.d.ts",
    ],
  },
];

export default eslintConfig;
