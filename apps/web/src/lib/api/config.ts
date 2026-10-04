/**
 * Runtime configuration. Everything here is NON-SECRET and browser-visible (NEXT_PUBLIC_*).
 * Never add keys or tokens here.
 */
export type ApiConfig = {
  /** Base URL of the FastAPI backend without trailing slash. Empty string = same origin. */
  baseUrl: string;
  /** True when the built-in mock API (Next route handlers) is the backend. */
  useMock: boolean;
};

export function resolveConfig(env: Record<string, string | undefined> = {
  NEXT_PUBLIC_API_BASE_URL: process.env.NEXT_PUBLIC_API_BASE_URL,
  NEXT_PUBLIC_USE_MOCK: process.env.NEXT_PUBLIC_USE_MOCK,
}): ApiConfig {
  const useMock = env["NEXT_PUBLIC_USE_MOCK"] === "1" || env["NEXT_PUBLIC_USE_MOCK"] === "true";
  // In mock mode the mock lives on the same origin (/api/*), so the base URL is ignored.
  const raw = useMock ? "" : (env["NEXT_PUBLIC_API_BASE_URL"] ?? "");
  return { baseUrl: raw.trim().replace(/\/+$/, ""), useMock };
}
