"use client";

import { getApiClient } from "@/lib/api";

/** Visible whenever the built-in mock API is the backend. The mock is a dev/test fixture, not product behaviour. */
export function MockBanner() {
  if (!getApiClient().config.useMock) return null;
  return (
    <div role="status" data-testid="mock-banner" className="bg-amber-300 px-4 py-1.5 text-center text-xs font-bold uppercase tracking-wide text-amber-950">
      MOCK API - dev/test fixture. Nothing here is real AI output, and no real action is taken.
    </div>
  );
}
