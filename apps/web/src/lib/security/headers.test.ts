import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { apiOrigin, buildCsp, securityHeaders } from "./headers";

const header = (name: string, opts = {}) => securityHeaders(opts).find((h) => h.key === name)?.value;

describe("security headers", () => {
  it("CSP forbids framing and plugins and restricts everything to self by default", () => {
    const csp = buildCsp();
    expect(csp).toContain("default-src 'self'");
    expect(csp).toContain("frame-ancestors 'none'");
    expect(csp).toContain("object-src 'none'");
    expect(csp).toContain("base-uri 'self'");
    expect(csp).toContain("form-action 'self'");
    expect(csp).toMatch(/img-src 'self' data:(;|$)/); // no remote images
  });

  it("only the API origin (not path, not wildcard) is added to connect-src", () => {
    const csp = buildCsp({ apiBaseUrl: "https://api.example.test:8443/v1/stuff" });
    expect(csp).toContain("connect-src 'self' https://api.example.test:8443;");
    expect(csp).not.toContain("*");
    expect(apiOrigin("javascript:alert(1)")).toBeUndefined();
    expect(apiOrigin("not a url")).toBeUndefined();
    expect(buildCsp({ apiBaseUrl: "javascript:alert(1)" })).toContain("connect-src 'self';");
  });

  it("'unsafe-eval' only in dev", () => {
    expect(buildCsp({ dev: true })).toContain("'unsafe-eval'");
    expect(buildCsp({ dev: false })).not.toContain("'unsafe-eval'");
    expect(buildCsp()).not.toContain("'unsafe-eval'");
  });

  it("sets the companion headers", () => {
    expect(header("X-Frame-Options")).toBe("DENY");
    expect(header("X-Content-Type-Options")).toBe("nosniff");
    expect(header("Referrer-Policy")).toBe("no-referrer");
    expect(header("Content-Security-Policy")).toContain("frame-ancestors 'none'");
  });

  it("next.config applies the headers to every path", async () => {
    const mod = await import("../../../next.config");
    const rules = await mod.default.headers!();
    const all = rules.find((r) => r.source === "/:path*");
    expect(all).toBeDefined();
    const csp = all!.headers.find((h) => h.key === "Content-Security-Policy")?.value ?? "";
    expect(csp).toContain("frame-ancestors 'none'");
    expect(csp).toContain("default-src 'self'");
  });
});

describe("no secrets in the browser bundle (SECURITY K4)", () => {
  const root = path.resolve(__dirname, "../../..");
  const SECRETY = /NEXT_PUBLIC_[A-Z0-9_]*(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)/;

  it(".env.example defines no secret-looking NEXT_PUBLIC_* variable", () => {
    const env = readFileSync(path.join(root, ".env.example"), "utf8");
    expect(env).not.toMatch(SECRETY);
  });

  it("source code never reads a secret-looking NEXT_PUBLIC_* variable", () => {
    const cfg = readFileSync(path.join(root, "src/lib/api/config.ts"), "utf8");
    expect(cfg).not.toMatch(SECRETY);
    const names = [...cfg.matchAll(/NEXT_PUBLIC_[A-Z0-9_]+/g)].map((m) => m[0]);
    expect(new Set(names)).toEqual(new Set(["NEXT_PUBLIC_API_BASE_URL", "NEXT_PUBLIC_USE_MOCK"]));
  });
});
