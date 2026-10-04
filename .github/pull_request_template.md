## Jira issue

<!-- Jira issue key, e.g. KAN-20. The branch name must be <type>/KAN-<number>-<description>
     with type in feature, bugfix, security, chore, docs. Do not invent keys. -->

## Branch

<!-- Paste the branch name. It must match the rule above (see CONTRIBUTING.md, "Branching"). -->

## Authoring agent

<!-- Who wrote this change: the agent code, e.g. "LR-04", or "human: <name>". Agents currently push through the
     repository owner's GitHub account, so this field and the commit message are the only attribution. They are
     NOT authenticated (anyone can type any text here); treat them as a statement of intent, not proof. -->

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

- [ ] Branch name matches `<type>/KAN-<number>-<description>` (type: feature, bugfix, security, chore or docs)
- [ ] Jira issue links to this PR (PR URL placed in the issue)
- [ ] If this PR returns work after review or failed checks: the Jira issue is In Progress with label `exec-rework` and an explanatory comment
- [ ] Independent review required before merge. The authoring agent does not merge; Ojas Sharma merges.
- [ ] CI is green (or failures are explained; no checks were disabled or weakened)
- [ ] No secrets, tokens or credentials in the diff
- [ ] Documentation updated (README/docs/ADR as applicable)
- [ ] Human approval obtained if this touches: production deployment, authn/authz, security policy, model/tool permissions, destructive migrations, sensitive-data policy, payment authority, irreversible external actions, safety-critical workflows, or a major-version release
