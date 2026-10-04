# apps/

**Purpose:** deployable user-facing applications. Per the baseline the web app is Next.js + TypeScript (doc 18 s1).

**Source:** directory skeleton from doc 19 (Start Here Bootstrap Guide) Step 2; technology baseline from doc 18 s1.

**Status:** `apps/api` (FastAPI backend, KAN-19) is the first app; it implements the frozen platform contract in `packages/contract/`. `apps/web` (Next.js) is owned by LR 05 and does not exist yet. Do not add other application code until the required ADRs exist. Doc 19 Step 12 puts UI refinement last in the build order.
