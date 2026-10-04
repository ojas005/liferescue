# Architecture Decision Records (ADRs)

The technology baseline in [`docs/baseline/18-TECHNICAL-ARCHITECTURE-v0_3.md`](../baseline/18-TECHNICAL-ARCHITECTURE-v0_3.md) "is a baseline and may be revised through ADRs" (doc 18 s1). Architecture decisions are recorded here as Markdown files named `NNNN-short-title.md` (for example `0001-source-control-host.md`).

Per doc 17 s1 and doc 16 s3, ADRs are the source of architectural decisions and rank above API/data contracts, tests, Jira metadata and agent suggestions when sources conflict.

## Status values

`Proposed` -> `Accepted` | `Rejected` | `Superseded by ADR-NNNN`. An ADR is only `Accepted` after human approval by the owner (Ojas Sharma). Agents may propose, not accept.

## Template

Copy this into a new file and fill in every section. If a section does not apply, write "None" and why.

```markdown
# ADR-NNNN: <title>

- Status: Proposed
- Date: YYYY-MM-DD
- Deciders: <humans/agents>
- Jira: <issue key or "pending project key decision">

## Context

<What situation, constraints and baseline-document references led here?>

## Problem

<The specific decision to be made.>

## Options

1. <Option A> - <summary>
2. <Option B> - <summary>

## Decision

<The chosen option. Left empty while Proposed.>

## Rationale

<Why this option; evidence.>

## Consequences

<What becomes easier/harder; follow-up work.>

## Security Impact

<Threats, controls, data exposure, approvals required.>

## Operational Impact

<Observability, cost, runbooks, on-call, DR.>

## Alternatives Rejected

<Options not chosen and why.>
```

## Proposed ADR topics (none written yet; proposals only)

Derived from the baseline documents; see the Confluence page "Open Decisions and Conflicts" for detail. Source control host and plan tier; Jira project key/issue types/workflow (REWORK); documentation source of truth; branch naming; backend stack; frontend stack; database and migrations; Redis usage; event bus product; object storage vendor; model gateway contract; customer inference models and fallback; separation of customer inference and engineering automation; hosting/cloud/IaC/registry; identity provider and OIDC; authorization model and policy engine; tool gateway; approval engine; incident state machine transitions; observability stack; CI platform and required checks; secret management and workforce credentials; data classification and retention; DR targets (RPO/RTO); workforce runtime; bot activation waves and review chain; research provider (Tavily) usage; API conventions.

## Index

| ADR | Title | Status |
|---|---|---|
| [ADR-0001](ADR-0001-jira-kan-schema-and-workflow-limitations.md) | Jira project KAN schema and workflow limitations | Accepted (interim), decided by Ojas Sharma 2026-10-03 |
| [ADR-0017](ADR-0017-jira-git-integration-and-status-mapping.md) | Jira/Git integration conventions and Jira status mapping | Proposed (the Jira status mapping was approved by Ojas Sharma 2026-10-04; every other part is Proposed; the ADR as a whole is not Accepted) |

File naming note: ADR-0001 uses the prefix `ADR-NNNN-` as requested by the owner; the naming text above (`NNNN-short-title.md`) is unchanged.
