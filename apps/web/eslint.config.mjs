import js from "@eslint/js";
import jsxA11y from "eslint-plugin-jsx-a11y";
import react from "eslint-plugin-react";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";
import tseslint from "typescript-eslint";

// Flat config. eslint-config-next is intentionally NOT used: its dependency chain
// (@next/eslint-plugin-next -> fast-glob -> micromatch -> braces) has an unpatched HIGH npm-audit advisory,
// which would fail the repo's `npm audit --audit-level=high` CI job. Re-evaluate when braces is patched.
export default tseslint.config(
  { ignores: ["src/lib/api/generated/**", ".next/**", "out/**", "build/**", "coverage/**", "next-env.d.ts", "node_modules/**"] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ["**/*.{ts,tsx,mjs}"],
    languageOptions: { globals: { ...globals.browser, ...globals.node } },
    plugins: { react, "react-hooks": reactHooks, "jsx-a11y": jsxA11y },
    settings: { react: { version: "detect" } },
    rules: {
      ...reactHooks.configs.recommended.rules,
      ...jsxA11y.flatConfigs.recommended.rules,
      "react/jsx-key": "error",
      "react/jsx-no-target-blank": "error",
      "react/jsx-no-script-url": "error",
      // Untrusted text (scam messages, URLs, web evidence) must never be injected as HTML (SECURITY U6).
      "react/no-danger": "error",
      "no-eval": "error",
      "no-implied-eval": "error",
      "@typescript-eslint/no-unused-vars": ["error", { argsIgnorePattern: "^_", varsIgnorePattern: "^_" }],
    },
  },
);
