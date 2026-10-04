// Verifies that src/lib/api/generated/openapi.d.ts is up to date with contract/openapi.yaml (CI-friendly, no network).
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const dir = mkdtempSync(join(tmpdir(), "lr-api-"));
const out = join(dir, "openapi.d.ts");
try {
  execFileSync("npx", ["openapi-typescript", "contract/openapi.yaml", "--default-non-nullable", "false", "-o", out], { stdio: "ignore" });
  const fresh = readFileSync(out, "utf8");
  const current = readFileSync("src/lib/api/generated/openapi.d.ts", "utf8");
  if (fresh !== current) {
    console.error("Generated API types are stale. Run: npm run gen:api");
    process.exit(1);
  }
  console.log("Generated API types match contract/openapi.yaml");
} finally {
  rmSync(dir, { recursive: true, force: true });
}
