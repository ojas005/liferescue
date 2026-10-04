/**
 * MOCK API route handlers (DEV/TEST ONLY).
 * Active only when NEXT_PUBLIC_USE_MOCK=1. Otherwise every request returns 404 so that this
 * catch-all can never be mistaken for the real backend. The real API is selected with NEXT_PUBLIC_API_BASE_URL.
 */
import { NextResponse, type NextRequest } from "next/server";
import { handleMockRequest } from "@/lib/mock/engine";

export const dynamic = "force-dynamic";

const MOCK_ENABLED = process.env.NEXT_PUBLIC_USE_MOCK === "1" || process.env.NEXT_PUBLIC_USE_MOCK === "true";

async function handle(req: NextRequest): Promise<NextResponse> {
  if (!MOCK_ENABLED) {
    return NextResponse.json({ error: "not_found", message: "Mock API is disabled. Set NEXT_PUBLIC_USE_MOCK=1 to enable it." }, { status: 404 });
  }
  let body: unknown;
  if (req.method !== "GET" && req.method !== "HEAD") {
    try {
      body = await req.json();
    } catch {
      return NextResponse.json({ error: "validation_error", message: "request body must be JSON" }, { status: 422 });
    }
  }
  const u = new URL(req.url);
  const res = handleMockRequest({ method: req.method, path: u.pathname + u.search, body });
  return NextResponse.json(res.body, { status: res.status, headers: { "X-Mock-Api": "1" } });
}

export const GET = handle;
export const POST = handle;

