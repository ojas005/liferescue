# Contributing to LifeRescue

This repository is built by humans and by a governed AI engineering workforce. These rules apply to **both**. They are drawn from the baseline documents in [`docs/baseline/`](docs/baseline/) (principally docs 16, 17 and 19). Anything the baseline does not define is marked **TBD** and must be decided through an ADR (see [`docs/adr/README.md`](docs/adr/README.md)).

## Ground rules

- No direct pushes to `main`. All changes arrive through a pull request (doc 16 s9, doc 19 step 3).
- Independent review required before merge.
- No self-approval and no self-merge (doc 16 s9, s11); the reviewer must not rely on the implementer's private reasoning. Separate GitHub identities for agents do not exist yet: agents push through the repository owner's account, so the "Authoring agent" field in the pull request is attribution by statement only, not proof of who wrote the change.
- Never disable, skip or weaken CI checks (including the secret scan) to get a change through.
- Never commit secrets, tokens, credentials or production data. See [`SECURITY.md`](SECURITY.md).
- If requirements conflict, security impact is unclear, scope expands materially, or production access seems necessary: stop and escalate (doc 16 s13).

## Branching

Branch names have the form `<type>/KAN-<number>-<description>` (decision by Ojas Sharma, 2026-10-04, KAN-20). The Jira project key is `KAN` (ADR-0001), so the branch carries the Jira issue key, for example `docs/KAN-20-contributing-branch-rules`.

| Part | Rule |
|---|---|
| `<type>` | exactly one of `feature`, `bugfix`, `security`, `chore`, `docs` (lowercase) |
| `KAN-<number>` | the Jira issue key; `<number>` is a positive integer without leading zeros (`KAN-20`, not `KAN-020`, not `KAN-KAN-20`) |
| `<description>` | short, lowercase words and digits (`a-z`, `0-9`) separated by single hyphens; no leading or trailing hyphen |

Reference regular expression (the validator in `scripts/` uses it as is):

```
^(feature|bugfix|security|chore|docs)/KAN-[1-9][0-9]*-[a-z0-9]+(-[a-z0-9]+)*$
```

The whole name must match: the validator uses `re.fullmatch` (an end-of-string anchor such as `\z` in other engines), because `$` alone accepts a trailing newline in some engines (Perl/PCRE, Python `re.match`/`re.search`, line-based `grep`). The validator does **no Unicode normalization**: full-width digits or letters, look-alike letters and similar are rejected as they are, and any other tool that checks branch names must not normalize (for example NFKC) before matching.

Valid: `feature/KAN-20-jira-git-integration`, `bugfix/KAN-7-fix-typo`, `docs/KAN-50-hosting-event-bus-environments-adr-proposals`.
Invalid: `feat/KAN-20-x` (the `feat` prefix is no longer allowed), `hotfix/KAN-20-x`, `feature/LR-20-x`, `feature/KAN-20` (no description), `feature/KAN-20-Desc` (uppercase), `feature/KAN-20-x_y` (underscore), `agent/lr04/KAN-20-x`.

Rules:

- Every new branch carries exactly one Jira key. Branches without a key are not used for new work; do not invent Jira keys.
- `feat/` is removed. Use `feature/`.
- Existing branches that do not match (for example `chore/bootstrap-repository-baseline`, `docs/KAN-orchestration-agent-assignment-registry`) are grandfathered; nothing is renamed or rewritten.
- Branch names are untrusted input in automation: tools must compare them with a fixed pattern and must never pass them to a shell unquoted or evaluate them.

> **Status of the details.** The five prefixes and the `KAN-<number>` key are decided (Ojas Sharma, 2026-10-04). The description format (lowercase kebab case), the maximum branch-name length of 100 characters, the one-key-per-branch rule and the grandfathering of existing branches are **proposed in ADR-0017, which is not yet accepted**. They are applied here so that the rule is checkable; they change if ADR-0017 is amended.
>
> A branch-name validator, `scripts/check-branch-name.py`, is delivered separately (KAN-20). A CI job that runs it is not configured yet (it is owned by the SRE/DevOps work item and changes `.github/workflows/`), and branch protection is not available on this repository plan, so until then a non-matching branch name is a review blocker by process, not a technical gate.

## Commits

- Small, focused commits with a clear imperative subject line.
- Reference the Jira issue key in the commit subject or body: `KAN-20: update branch naming rules`. Use `KAN-<number>`; the earlier `LR-123` examples no longer apply.
- Signed commits are expected "where practical" (doc 19 step 3). Enforcement is not configured yet.

## Pull requests

Use the template in [`.github/pull_request_template.md`](.github/pull_request_template.md). It requires:

1. Jira issue
2. Branch
3. Authoring agent (the agent code, for example `LR-04`, or `human: <name>`; not authenticated)
4. Problem
5. Solution
6. Implementation details
7. Tests (a link to the run or a summary of the real results; no raw logs)
8. Security impact
9. Operational impact
10. Deployment impact
11. Rollback plan

Put the Jira key (`KAN-<number>`) and the branch name in the PR, and put the PR URL in the Jira issue (comment or remote link) (doc 17 s10, s14: Jira -> branch -> PR -> CI/Security/QA -> release -> observability).

If a PR returns work to its owner after failed checks, requested changes or a failed gate (rework), the Jira issue is moved from **In Review** back to **In Progress**, gets the label **`exec-rework`** and an explicit Jira comment giving the reason, the evidence link and what completes the rework. The label is removed when the rework is complete. See [`docs/jira-comment-label-conventions.md`](docs/jira-comment-label-conventions.md) for the comment formats; every format carries a `by:` field (who wrote the comment), and evidence is always a link, never pasted logs or output.

## Review rules

- Independent review required before merge.
- At least one reviewer who did not write the change. (Enforced branch protection is **not currently available** on this repository plan; see `README`/`docs/overview.md`. Until it is enabled this rule is a process rule.)
- Required automated checks must pass: see [`.github/workflows/ci.yml`](.github/workflows/ci.yml). Stages that are not yet active are listed in `docs/overview.md`.
- Recommended chain (doc 16 s11): implementation -> CI -> Security -> QA -> independent reviewer -> human approval where required -> release.
- Human approval is **always** required for: production deployment; authentication/authorization changes; security-policy changes; model/tool-permission changes; destructive migrations; sensitive-data policy changes; external payment authority; irreversible external actions; safety-critical workflow changes; major-version releases.
- Code owners are defined in [`CODEOWNERS`](CODEOWNERS) (currently `@ojas005` for all paths).

## Definition of Done (doc 17 s7)

Implementation merged; CI passed; required tests passed; security checks completed; observability added; documentation updated; acceptance criteria verified; deployment status known; Jira links synchronized.

## Architecture changes

Changes to the technology baseline (doc 18) go through an ADR. Proposed ADR topics are tracked in the Confluence page "Open Decisions and Conflicts".
