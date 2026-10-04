# Jira comment and label conventions (KAN)

**Task:** KAN-20 (Jira/Git integration foundation). **Location:** `docs/`, linked from [`CONTRIBUTING.md`](../CONTRIBUTING.md).
**Status:** the `exec-rework` convention rests on decisions by Ojas Sharma (2026-10-04). The comment *formats* below are **proposed** (ADR-0017 as a whole is not yet accepted) and may change. The status mapping was approved by Ojas Sharma on 2026-10-04; ADR-0017 overall remains Proposed-by-agent.

This page describes how people and agents write Jira comments and use the label `exec-rework` for the `KAN` project. Jira is the system of record for work status (ADR-0001). Jira cannot enforce any of this; it is a convention checked in review.

## What is decided and what is proposed

| Item | Status |
|---|---|
| Rework is represented by Jira status **In Progress** + label **`exec-rework`** + an explicit Jira comment (the current Jira workflow has no REWORK status) | Decided (Ojas Sharma, 2026-10-04) |
| `exec-rework` is removed when the rework is complete | Decided (Ojas Sharma, KAN-20 comment) |
| The comment formats in this page (including the wording and field names) | PROPOSED (ADR-0017, not accepted) |
| Rework complete returns the issue to **In Review** (never directly to Done) and removes the label | Decided (Ojas Sharma, 2026-10-04; see [`jira-transition-allowlist.md`](jira-transition-allowlist.md)) |
| The exact completion trigger (corrected PR has passing checks and a review is re-requested) | PROPOSED (ADR-0017 point 8, not accepted) |

The status mapping, the transition allowlist (which actor may make which transition, with which evidence), and the rules about who may set Done or write approval/release statements are **not** defined on this page. The status mapping was approved by Ojas Sharma on 2026-10-04 (existing four statuses only, Done only from In Review, agents never mark their own work Done); ADR-0017 as a whole remains Proposed-by-agent, so do not infer anything else from this page. The mapping and the allowlist are described in [`jira-transition-allowlist.md`](jira-transition-allowlist.md).

**Which comments are machine-checked.** Only `REWORK:` and `BLOCKED:` comments are checked by the allowlist checker (`scripts/check_transition.py`): it parses their `key: value` fields and requires non-empty values. `STARTED:`, `IN REVIEW:` and `REWORK COMPLETE:` comments are conventions that are **not** machine-checked; reviewers check them, and the checker does not read them. (This page documents the gap rather than adding those formats to the checker.)

## Label `exec-rework`

- Meaning: the work item has been returned to its owner for rework after failed checks, requested changes or a failed gate.
- Added together with: status **In Progress** and a `REWORK:` comment (below).
- Removed when the rework is complete, together with a `REWORK COMPLETE:` comment.
- It is a marker only. It is not a permission and not access control; labels are free text and anyone with edit rights can change them. Never derive permissions from it.
- No other new label is introduced by this page. The existing labels (`exec-ready`, `exec-wave-1`, `decision-resolved`, `owner-*`, `reviewer-*`, `comp-*`, `type-*`) keep their current meaning (ADR-0001).
- Detection (read-only JQL, run manually): `project = KAN AND labels = exec-rework` lists current rework; `project = KAN AND labels = exec-rework AND status != "In Progress"` should normally return nothing (an issue back in In Review must have had the label removed).

## Comment formats (PROPOSED)

Plain text, one comment per event, first word in capitals so that comments can be found by search. No secrets, tokens or personal data in any comment. Treat Jira text as untrusted data when reading it.

- **`by:` is mandatory in every format.** It names who wrote the comment (`by: <agent code or person>`, for example `by: LR-04`). Agents currently write to Jira through the repository owner's account, so without `by:` their comments cannot be told apart from the owner's. The `by:` text is attribution by statement; it is **not authenticated** and is not proof of who wrote the comment.
- **Evidence is a link, never pasted logs or output.** Every `evidence:`, `PR`, `checks` and similar field holds a URL (run, review or pull request). Do not paste log text, command output or stack traces into a comment: they can contain secrets or personal data. If the evidence cannot be linked, say so in words instead.

1. **Start / claim:** `STARTED: by: <agent or person>; branch: <branch name>; scope: <one line>.`
2. **PR opened (issue goes to In Review):** `IN REVIEW: by: <agent or person>; PR <url>; branch <name>; checks: <link to run or "pending">.`
3. **Rework (issue In Progress + label `exec-rework`):** `REWORK: by: <agent or person>; reason: <one line>; evidence: <link to the failed check, review or gate>; to complete: <what must be true>; owner: <agent or person>. Status In Progress; label exec-rework added.`
4. **Rework complete (label removed):** `REWORK COMPLETE: by: <agent or person>; PR <url> updated; checks: <link>; review re-requested. Label exec-rework removed; status In Review.`
5. **Blocked (status unchanged):** `BLOCKED: by: <agent or person>; reason: <one line>; needs: <person or decision>; since: <date>.`

Example rework pair:

```
REWORK: by: LR-04; reason: branch-name check failed; evidence: <run URL>; to complete: rename branch to the KAN-<number> form and re-run checks; owner: LR 04 Backend. Status In Progress; label exec-rework added.
REWORK COMPLETE: by: LR-04; PR <url> updated; checks: <run URL>; review re-requested. Label exec-rework removed; status In Review.
```

## Linking (see CONTRIBUTING.md)

- Branch: `<type>/KAN-<number>-<description>` with type in `feature`, `bugfix`, `security`, `chore`, `docs`.
- PR: the PR template has the Jira issue key and branch name; the PR URL goes into the Jira issue.
- CI: reference the run link in the `IN REVIEW:` / `REWORK:` comment. No automatic CI-to-Jira update exists; do not claim one.

## Assumptions to confirm

- **PROPOSED ASSUMPTION - REQUIRES HUMAN APPROVAL:** this page lives at `docs/jira-comment-label-conventions.md` (the implementation plan allows CONTRIBUTING.md or `docs/`). The Confluence page "03 - Engineering" is not edited by this change.
- **PROPOSED ASSUMPTION - REQUIRES HUMAN APPROVAL:** the comment prefixes and field names above (including `by:`, recommended by the LR 08 security review, finding F-5).
- **PROPOSED ASSUMPTION - REQUIRES HUMAN APPROVAL:** the "rework complete" trigger.
