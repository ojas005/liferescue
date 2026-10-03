# LifeRescue - Repository Overview

> This file carries the README content produced by the bootstrap run. The repository's root `README.md` (30 bytes: `# liferescue` / `Hackathon NVIDIA`) pre-existed and was intentionally **not modified**. The owner can merge this content into `README.md` in a follow-up change.

## Purpose

LifeRescue is an incident-coordination product built by a governed AI engineering workforce (docs 16 and 19). The repository description is "Hackathon NVIDIA"; hackathon rules are not documented in the baseline (documentation gap).

The baseline principle (doc 16 s1): *Agents may propose and implement changes inside bounded authority; production authority remains governed by policy and human approval.* Golden rule (doc 19): ask "What is the next verified product capability required by the roadmap, and what evidence proves it is complete?" rather than "What can the AI build next?".

## Status

Pre-implementation bootstrap. No application code exists. Do not start by building the UI (doc 19 Goal): the engineering control system comes first.

## Architecture overview (doc 18 v0.3 - baseline, revisable through ADRs)

Baseline stack: Next.js + TypeScript (web); Python + FastAPI (API); Python (agent runtime); PostgreSQL; Redis; managed event bus (product TBD); S3-compatible object storage (vendor TBD); AI inference via Nebius AI Cloud / Token Factory with NVIDIA open models such as Nemotron; Tavily for research; Grok/xAI tooling for the engineering workforce; Jira + Confluence; GitHub or Bitbucket (actual: GitHub); Docker; Terraform; OpenTelemetry.

Service boundaries: API Gateway/BFF, Incident Service, Agent Orchestrator, Policy Engine (the LLM is never the final policy authority), Tool Gateway (single governed boundary for all external actions), Evidence Service, Notification Service, Verification Service. Domain services are never coupled directly to one model provider (AI Model Gateway). Incident state machine and approval engine are specified in doc 18 s8 and s10. See [`docs/baseline/18-TECHNICAL-ARCHITECTURE-v0_3.md`](baseline/18-TECHNICAL-ARCHITECTURE-v0_3.md).

Undecided (no ADR yet): hosting/cloud, event bus product, identity provider, observability backend, secret manager, CI/CD details beyond GitHub Actions in this repo, RPO/RTO.

## Repository structure

```text
apps/            user-facing applications (empty)
services/        backend services (empty)
packages/        shared libraries (empty)
agents/          agent runtime and workflows (empty)
tools/           tool definitions/adapters (empty)
infrastructure/  Terraform/Docker/environments (empty)
tests/           cross-service tests (empty)
scripts/         repository automation scripts
docs/            baseline docs, ADRs, workforce registry
  baseline/      the five baseline documents, verbatim, plus manifest.json
  adr/           ADR template and index
  workforce/     agent registry
.github/         CI workflow and pull request template
```

Each skeleton directory has a short README stating its purpose and source document.

## Development setup

**TBD.** Local development, formatting, linting and type-check tooling are part of the "Repository Bootstrap" task (doc 19 LR-3) and are not defined in the baseline. Do not assume tools; add them via a reviewed PR and extend CI accordingly.

## Testing

TBD per stack. Doc 19 Step 9 target pipeline: checkout, dependency install, format check, lint, type check, unit tests, integration tests, security scan, secret scan, build, artifact. A failed pipeline must block release.

## Security

See [`SECURITY.md`](../SECURITY.md). Highlights: no secrets in the repo; secret scan in CI; least-privilege credentials; human approval for production and policy changes.

## CI/CD

`.github/workflows/ci.yml` runs on pull requests and pushes to `main` with `permissions: contents: read` and actions pinned by commit SHA.

| Stage (doc 19 step 9) | State |
|---|---|
| Checkout | Active |
| Secret scan (gitleaks) | **Active** |
| Repository structure validation, Markdown link check | **Active** (these are repo-specific substitutes, not in doc 19) |
| Dependency install | Inactive until project manifests exist (conditional jobs) |
| Format check, Lint, Type check | Inactive until project files exist (conditional jobs for Node/Python) |
| Unit tests, Integration tests | Inactive until tests exist (conditional jobs) |
| Dependency (security) scan | Inactive until manifests exist (conditional job) |
| SBOM | Inactive until manifests exist (conditional job) |
| Build, Artifact | **Not implemented** (no build exists; no job claims it) |
| Deployment | **Not implemented**; production deployment needs human approval |

"Inactive" jobs are skipped by `if:` conditions and are reported as skipped; they are untested in this repository until real project files exist.

## Agent workforce

The engineering workforce (docs 16, 20) is described in [`docs/workforce/agent-registry.md`](workforce/agent-registry.md): 14 registered agents (LR 01-LR 14), Wave 1 = Product Manager, Architect, Backend Engineer, QA/Evaluation, Security Engineer with Orchestrator as hub; the others are registered but not activated. Per-bot limits (model, budgets, timeouts) are TBD.

## Jira workflow

Doc 17 defines: Initiative > Epic > Story/Task > Sub-task; workflow BACKLOG, READY, IN PROGRESS, IN REVIEW, IN VALIDATION, READY FOR RELEASE, RELEASED, DONE, plus BLOCKED, REJECTED, CANCELLED (REWORK is referenced but not defined). The Jira project key is an **open decision** (docs say `LR`; as of 2026-10-03 the live Jira site has project `KAN` and no `LR`). See the Confluence "Open Decisions and Conflicts" page.

## Contribution workflow

See [`CONTRIBUTING.md`](../CONTRIBUTING.md): branch from `main`, reference Jira (once a key exists), open a PR using the template, CI must pass, independent review, no self-merge.

## Known limitations of this repository's settings (read on 2026-10-03)

- Branch protection / rulesets: API returned HTTP 403 ("Upgrade to GitHub Pro or make this repository public"). `main` is **not protected**.
- Secret scanning (platform), Dependabot alerts and code scanning: **disabled**.
- Required reviewers, required status checks, signed commits: not enforced.
