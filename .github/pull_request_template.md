## Jira issue

<!-- Jira key (e.g. LR-123). If the Jira project/key is not yet decided write: "Jira: pending project key decision". Do not invent keys. -->

## Problem

<!-- What is wrong or missing? Link requirements / ADRs. -->

## Solution

<!-- What does this change do, in one paragraph? -->

## Implementation details

<!-- Key design points, files/areas touched, deviations from the baseline docs. -->

## Tests

<!-- Tests added/updated and how to run them. Paste real results; do not claim checks that did not run. -->

## Security impact

<!-- Secrets, authn/authz, data exposure, dependencies, prompt/tool permissions. State "none" only if you checked. -->

## Operational impact

<!-- Observability, performance, cost, migrations, runbooks. -->

## Deployment impact

<!-- Config/infrastructure changes, rollout steps, feature flags. -->

## Rollback plan

<!-- How to undo this change safely. -->

## Checklist

- [ ] Author and reviewer are different identities (no self-approval, no self-merge)
- [ ] CI is green (or failures are explained; no checks were disabled or weakened)
- [ ] No secrets, tokens or credentials in the diff
- [ ] Documentation updated (README/docs/ADR as applicable)
- [ ] Human approval obtained if this touches: production deployment, authn/authz, security policy, model/tool permissions, destructive migrations, sensitive-data policy, payment authority, irreversible external actions, safety-critical workflows, or a major-version release
