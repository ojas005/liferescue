/**
 * Security response headers for the web app (SECURITY A5, U6, K4).
 * Pure functions so they can be unit-tested and reused by next.config.ts.
 *
 * KNOWN LIMITATION: Next.js emits inline bootstrap scripts, so script-src needs 'unsafe-inline' unless a per-request
 * nonce is wired through middleware (needs dynamic rendering for every page). Mitigation in this slice: the UI never
 * renders HTML from data (no dangerouslySetInnerHTML; lint rule react/no-danger = error). Revisit with a nonce CSP
 * before any public deploy.
 */
export type HeaderOptions = {
  /** NEXT_PUBLIC_API_BASE_URL; only its ORIGIN is added to connect-src. Empty/invalid = same origin only. */
  apiBaseUrl?: string;
  /** Development needs 'unsafe-eval' (React refresh). Never set in production builds. */
  dev?: boolean;
};

export function apiOrigin(apiBaseUrl: string | undefined): string | undefined {
  if (!apiBaseUrl) return undefined;
  try {
    const u = new URL(apiBaseUrl);
    return u.protocol === "http:" || u.protocol === "https:" ? u.origin : undefined;
  } catch {
    return undefined;
  }
}

export function buildCsp(opts: HeaderOptions = {}): string {
  const connect = ["'self'", apiOrigin(opts.apiBaseUrl)].filter((x): x is string => Boolean(x));
  const directives: Record<string, string[]> = {
    "default-src": ["'self'"],
    "script-src": ["'self'", "'unsafe-inline'", ...(opts.dev ? ["'unsafe-eval'"] : [])],
    "style-src": ["'self'", "'unsafe-inline'"],
    // No remote images: image URLs in untrusted text are an exfiltration channel (U6).
    "img-src": ["'self'", "data:"],
    "font-src": ["'self'"],
    "connect-src": connect,
    "object-src": ["'none'"],
    "base-uri": ["'self'"],
    "form-action": ["'self'"],
    "frame-ancestors": ["'none'"],
  };
  return Object.entries(directives)
    .map(([k, v]) => `${k} ${v.join(" ")}`)
    .join("; ");
}

export function securityHeaders(opts: HeaderOptions = {}): { key: string; value: string }[] {
  return [
    { key: "Content-Security-Policy", value: buildCsp(opts) },
    { key: "X-Frame-Options", value: "DENY" },
    { key: "X-Content-Type-Options", value: "nosniff" },
    { key: "Referrer-Policy", value: "no-referrer" },
    { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), payment=()" },
  ];
}
