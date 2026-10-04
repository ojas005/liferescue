# Jira status mapping and transition allowlist (KAN)

**Task:** KAN-20 (Jira/Git integration foundation), work item WI-04-6. **Data file:** [`scripts/jira-transition-allowlist.json`](../scripts/jira-transition-allowlist.json). **Checker:** [`scripts/check_transition.py`](../scripts/check_transition.py) with tests in [`scripts/test_check_transition.py`](../scripts/test_check_transition.py).

Jira cannot enforce any of this (the KAN project has a fixed four-status workflow, see [ADR-0001](adr/ADR-0001-jira-kan-schema-and-workflow-limitations.md)). The allowlist is for integration code and reviewers: KAN-26 and KAN-27 must import it instead of writing their own rules, and nothing in this repository calls Jira. **The checker trusts the caller-declared `actor_type`: that is a consistency check on what the caller says, not access control. Anyone who can call it can claim to be `human`, so KAN-26 must derive the actor from an authenticated identity (never from request text) before it calls the checker.** The comment and label wording is described separately in `docs/jira-comment-label-conventions.md` (added by branch `docs/KAN-20-contributing-branch-rules`; it is not on this branch, so it is not linked here).

## What is approved and what is not

| Item | Status |
|---|---|
| Existing Jira workflow only: **To Do / In Progress / In Review / Done**. No new statuses. | **Approved** (Ojas Sharma, 2026-10-04 07:28 IST, ADR-0017 status mapping) |
| BLOCKED and REWORK are labels/comments, not statuses. REWORK = In Progress + label `exec-rework` + explicit comment | **Approved** (same decision; `exec-rework` also KAN-20 comments 10108/10113) |
| Agents may move work to In Progress / In Review according to evidence | **Approved** |
| An agent must **never** declare its own work Done. Done needs validation, required review, acceptance-criteria evidence and merge/release conditions (human approval for sensitive work) | **Approved** |
| ADR-0017 itself | still `Proposed-by-agent` in its own file; only the mapping above was approved |
| **Authoritative status model** (Ojas Sharma via LR 01, 2026-10-04): Done is reachable **only from In Review**, for every actor including a human; a human approves completion but the transition rules and the acceptance evidence still apply (a human cannot skip evidence); rework is never sent directly to Done and never read as completed work | **Approved** |
| Rework lifecycle: In Review -> REWORK REQUIRED -> In Progress (+ label `exec-rework` + explicit reason comment) -> fix -> In Review -> review -> Done. REWORK REQUIRED is the outcome of a review or failed check, not a Jira status | **Approved** |
| Everything else in this page (exact actor lists per transition, evidence field names, the `REWORK:`/`BLOCKED:` comment shape including the mandatory `by:` field, the https-only URL rule, the heuristic for approval/release wording, the absence of a `blocked` label) | **PROPOSED ASSUMPTION - REQUIRES HUMAN APPROVAL** |

## Statuses and actors

Statuses: `To Do`, `In Progress`, `In Review`, `Done`. Actor types in the data file:

| Actor type | Kind | Meaning |
|---|---|---|
| `human` | human | A person (for example Ojas Sharma). The only actor that may touch Done. |
| `owner_agent` | agent | The agent that owns the work item. |
| `reviewer_agent` | agent | A reviewer, QA or security gate agent acting manually. |
| `automation` | automation | Webhook, CI step, scheduled job, adapter or script. No adapter exists yet (KAN-26). |

## Transition allowlist

Anything not listed is denied. "Evidence" is checked for presence and shape only (see Limits).

| Id | From -> To | Actors | Evidence (all rows must be satisfied) | Source |
|---|---|---|---|---|
| `start_work` | To Do -> In Progress | owner_agent, human, automation | `claim_record` or `branch_name` | ADR-0017 pt 11 |
| `open_for_review` | In Progress -> In Review (label `exec-rework` absent) | owner_agent, human, automation | `pr_url` and a valid `branch_name` | ADR-0017 pt 11 |
| `send_to_rework` | In Review -> In Progress | reviewer_agent, owner_agent, human, automation | `failed_check_or_review_url` (a link); label `exec-rework` added; comment `REWORK: by: ...; reason: ...; evidence: <link>; to complete: ...` | approved REWORK rule; ADR-0017 pts 8, 11 |
| `complete_rework` | In Progress -> In Review (label `exec-rework` present) | owner_agent, human, automation | `passing_checks_url` and `review_rerequested: true`; label `exec-rework` removed | ADR-0017 pts 8, 11 |
| `return_to_todo` | In Progress / In Review -> To Do | human | `reason` | ADR-0017 pt 11 |
| `accept_done` | In Review -> **Done** (the only way to Done; denied while label `exec-rework` is present) | **human only** | `validation_url`, `review_approval_url`, `acceptance_criteria_verified: true`, `acceptance_verified_by`, `merged_pr_url`, `release_ref` or `no_release_required: true`, explicit `sensitive_work` (and `human_approval_ref` when it is true) | approved Done rule; plan template 7 and section 12 |
| `reopen` | Done -> To Do / In Progress / In Review | human | `reason` | ADR-0017 pt 11 |
| `blocked` (status unchanged) | To Do / In Progress / In Review | human, owner_agent, reviewer_agent | comment `BLOCKED: by: ...; reason: ...` | ADR-0017 pt 10 |

Rules that apply to every request:

- **Done has exactly one way in: `accept_done`, from In Review, by a human, with the evidence listed above.** Every other status -> Done is denied for every actor, including a human (tests cover the full matrix). The data file and the schema check enforce this, and the schema check also requires that Done is denied while `exec-rework` is present.
- **No agent or automation path reaches Done.** `owner_agent`, `reviewer_agent` and `automation` are denied `-> Done` and `Done -> any`. This is enforced three times: the data file lists only `human` on those rows, the schema check rejects a file that lists anything else (and checks reachability for every non-human actor), and the checker has a hard-coded guard that does not read the file. Tests prove each layer, including a mutation check that fails when the guard is removed.
- Approval, acceptance and release statements (`APPROVED:`, `ACCEPTED:`, `DONE:`, `RELEASED:` in a comment, or an added label containing approved/accepted/released/done) are denied for `automation` and `owner_agent`. `reviewer_agent` may write `APPROVED:` only with a `review_url` and only when `actor_id` differs from `owner_id` (no self-approval). `DONE:`, `ACCEPTED:` and `RELEASED:` are human only. This wording check is a heuristic on free text, not a security boundary.
- `exec-rework` may only be present in status `In Progress`. After any other status change it must be gone.
- **`exec-rework` changes only on its own transitions.** Adding or removing the label is allowed only in `send_to_rework`, `complete_rework`, `return_to_todo` and `reopen` (hard-coded in the checker, whatever the data file says). A `BLOCKED:` note (status unchanged) or any other transition that adds or removes it is denied for every actor, so a BLOCKED note cannot skip the rework-complete evidence.
- **Reopening into rework needs a REWORK comment.** A `reopen` from Done to In Progress that leaves `exec-rework` on the issue must carry a valid `REWORK:` comment (same fields as `send_to_rework`); otherwise it is denied. Reopening to To Do or In Review with the label is denied outright.
- **Label matching is case-insensitive and fails closed.** Labels are compared case-folded, with `_`, `.` and `:` read as `-`, so `Exec-Rework`, `EXEC_REWORK` and `exec.rework` all count as `exec-rework` (for the Done exclusion, the In-Progress-only rule and the add/remove rules above). A label with whitespace, control characters or look-alike Unicode (for example a non-breaking hyphen, a full-width letter or a Cyrillic letter) is malformed and the whole request is denied; the checker never reads it as "no `exec-rework`".
- **Rework lifecycle** (`rework_lifecycle` in the data file, checked against the transitions): `REWORK REQUIRED` (review or gate outcome, In Review, nothing moves yet) -> `send_to_rework` (In Progress, label + reason comment) -> fix (In Progress) -> `complete_rework` (back to In Review, label removed, review re-requested) -> review -> `accept_done`. Rework is never sent directly to Done and never read as completed work.
- Every comment format carries `by: <agent or person>`; evidence is a link, never pasted logs. `by:` is attribution by statement, not authentication.
- **Comment fields are parsed, not searched.** The checker reads a `REWORK:` or `BLOCKED:` comment as `key: value` fields separated by `;` (each split at its first colon; a segment without a colon is free text and is ignored). `REWORK:` needs non-empty `by`, `reason`, `to complete` and an `evidence` value that is an acceptable https URL (below). `BLOCKED:` needs non-empty `by` and `reason`; other fields such as `needs:` or `since:` are optional and unchecked. A missing field, an empty value (`by:;`), a repeated field, a value with no letters or digits, an unfilled `<placeholder>`, a value over 300 characters, or a non-URL evidence value (for example `evidence: Traceback token=abc123`) is denied. Only `REWORK:` and `BLOCKED:` comments are machine-checked; `STARTED:`, `IN REVIEW:` and `REWORK COMPLETE:` are not read by the checker.
- **Evidence URLs** (every `url` evidence field and the `evidence:` field of a REWORK comment): `https://` only (no `http`, `ftp`, `file`, `javascript` or scheme-relative forms); no user information (`user:pass@host`); no IP address in any notation (dotted, decimal, hex, octal or `[IPv6]`); and the host must be a domain name with a letters-only last label (so `localhost` and bare intranet names are refused too). Optional host allowlist: the data file key `evidence_url_hosts` is a list of lowercase domain names; when it is non-empty the URL host must equal one of them (exact match, case-insensitive, sub domains are not implied). It ships empty, which means off. This is a shape check on the text, not a check that the link is reachable or safe.
- Labels never grant permission. Unknown actors, statuses, transitions, evidence fields, malformed values (non-text, newlines or control characters, non-https URLs, invalid branch names) and a missing comment or evidence all give "deny".
- BLOCKED has no status and no label name: ADR-0017 defines only the comment. A `blocked` label name is **PROPOSED ASSUMPTION - REQUIRES HUMAN APPROVAL** and is recorded as `null` in the data file.

## Using the checker

```
python3 scripts/check_transition.py --validate-allowlist
python3 scripts/check_transition.py --request request.json
python3 -m unittest -v scripts/test_check_transition.py
```

From code: `check_transition(from_status, to_status, actor_type, labels_before, labels_after, evidence=None, comment=None, actor_id=None, owner_id=None)` returns `Decision(allowed, transition_id, reasons)`. Standard library only; no network, no subprocess, no evaluation of input. An integration-style test exists only as a skipped stub behind `KAN20_RUN_INTEGRATION_TESTS=1`; it makes no call because the non-production Jira project it needs has not been approved.

## Limits (be honest about what this does not prove)

- The checker trusts the caller-declared `actor_type` (see the top of this page): it is a consistency check, not access control, and KAN-26 must derive the actor from an authenticated identity.
- The checker verifies the **shape** of evidence (for example "this is an https URL"). It cannot know that a check really passed or that a review really approved. A human still reads the evidence.
- Labels and comments are free text; anyone with edit rights can change them. The read-only detection queries from ADR-0017 remain necessary (Done set by a non-human changelog author; `labels = exec-rework AND status != "In Progress"`; PR head branches that fail the pattern).
- It is not wired into CI or any adapter. That is KAN-26/KAN-27 (and `.github/workflows/*` belongs to LR 10).

## Relation to ADR-0017

ADR-0017 was updated by LR 03 on 2026-10-04 (ref t22u) to carry the decisions below; this page and the data file follow that text (rows T1-T8 of point 11 and points 15-16). This page does not edit the ADR. Remaining differences, all marked PROPOSED ASSUMPTION - REQUIRES HUMAN APPROVAL and listed for LR 03 in `evidence/ADR-0017-edits-for-LR03.md` (outside this repository):

- Decided and implemented here: Done only from In Review for every actor (ADR D6, rows T5/T6); rework-complete is In Progress -> In Review (D7, T4); `human` is an actor for rework-complete and `owner_agent` for send-to-rework (D8).
- The ADR does not yet mention the mandatory `by:` field in comments or the rule that evidence is a link (LR 08 findings F-5), nor the full list of acceptance-evidence fields used for `accept_done`, nor the rule that Done is denied while `exec-rework` is present.
- ADR-0017 T3 treats the failed-check or review URL as proposed evidence; the data file requires it.
