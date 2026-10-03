# Contributing to LifeRescue

This repository is built by humans and by a governed AI engineering workforce. These rules apply to **both**. They are drawn from the baseline documents in [`docs/baseline/`](docs/baseline/) (principally docs 16, 17 and 19). Anything the baseline does not define is marked **TBD** and must be decided through an ADR (see [`docs/adr/README.md`](docs/adr/README.md)).

## Ground rules

- No direct pushes to `main`. All changes arrive through a pull request (doc 16 s9, doc 19 step 3).
- No self-approval and no self-merge. The author and the reviewer must be different identities (doc 16 s9, s11). For agents, the implementer and reviewer are separate agent identities; the reviewer must not rely on the implementer's private reasoning.
- Never disable, skip or weaken CI checks (including the secret scan) to get a change through.
- Never commit secrets, tokens, credentials or production data. See [`SECURITY.md`](SECURITY.md).
- If requirements conflict, security impact is unclear, scope expands materially, or production access seems necessary: stop and escalate (doc 16 s13).

## Branching

The baseline (doc 17 s10) uses branches of the form `feat/LR-123-incident-create`, i.e. `<type>/<JIRA-KEY>-<short-description>`.

> **Status: the naming convention and the Jira project key are not final.** The user brief proposes the prefixes `feature|bugfix|security|chore|docs`, and the Jira project key (`LR` in the docs vs `KAN` in the live Jira site) is still an open decision. Until it is decided, use `<type>/<JIRA-KEY>-<short-description>` with `<type>` in `feat|feature|bugfix|security|chore|docs`, and where no Jira key exists yet use `<type>/<short-description>` and state "Jira: pending project key decision" in the PR. Do not invent Jira keys.

The first bootstrap branch (`chore/bootstrap-repository-baseline`) follows this exception.

## Commits

- Small, focused commits with a clear imperative subject line.
- Reference the Jira issue in the commit message body or subject once it exists: `LR-123: add incident creation endpoint`. Before a key exists write `Jira: pending project key decision`.
- Signed commits are expected "where practical" (doc 19 step 3). Enforcement is not configured yet.

## Pull requests

Use the template in [`.github/pull_request_template.md`](.github/pull_request_template.md). It requires:

1. Jira issue
2. Problem
3. Solution
4. Implementation details
5. Tests (real results only)
6. Security impact
7. Operational impact
8. Deployment impact
9. Rollback plan

Link the PR from the Jira issue and the Jira key in the PR (doc 17 s10, s14: Jira -> branch -> PR -> CI/Security/QA -> release -> observability).

## Review rules

- At least one reviewer who is not the author. (Enforced branch protection is **not currently available** on this repository plan; see `README`/`docs/overview.md`. Until it is enabled this rule is a process rule.)
- Required automated checks must pass: see [`.github/workflows/ci.yml`](.github/workflows/ci.yml). Stages that are not yet active are listed in `docs/overview.md`.
- Recommended chain (doc 16 s11): implementation -> CI -> Security -> QA -> independent reviewer -> human approval where required -> release.
- Human approval is **always** required for: production deployment; authentication/authorization changes; security-policy changes; model/tool-permission changes; destructive migrations; sensitive-data policy changes; external payment authority; irreversible external actions; safety-critical workflow changes; major-version releases.
- Code owners are defined in [`CODEOWNERS`](CODEOWNERS) (currently `@ojas005` for all paths).

## Definition of Done (doc 17 s7)

Implementation merged; CI passed; required tests passed; security checks completed; observability added; documentation updated; acceptance criteria verified; deployment status known; Jira links synchronized.

## Architecture changes

Changes to the technology baseline (doc 18) go through an ADR. Proposed ADR topics are tracked in the Confluence page "Open Decisions and Conflicts".
