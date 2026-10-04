# ADR-0017: Jira/Git integration conventions and Jira status mapping

- Status: Proposed. **Ojas Sharma approved the Jira status mapping on 2026-10-04.** That approval covers only the parts tagged "Approved" in this file (the four-status model, Done reachable only from In Review, no agent self-Done, human approval for sensitive and release-critical completion, and the rework lifecycle with its actors). Every other part is tagged "Proposed" and is not accepted. The ADR as a whole is not `Accepted`; only Ojas Sharma can accept it (see `README.md`).
- Date: 2026-10-04
- Deciders: Ojas Sharma (decision owner). Drafted by the Architect agent (LR 03); agents may propose, not accept. Additions marked "LR 04-proposed" were proposed by the Backend agent (LR 04) after implementing the allowlist.
- Jira: KAN-20 (Jira/Git Integration). Affects KAN-19, KAN-26, KAN-27 and KAN-21.
- Related: [ADR-0001](ADR-0001-jira-kan-schema-and-workflow-limitations.md), [`docs/jira-comment-label-conventions.md`](../jira-comment-label-conventions.md), [`docs/jira-transition-allowlist.md`](../jira-transition-allowlist.md), [`CONTRIBUTING.md`](../../CONTRIBUTING.md).

## Tags used in this file

| Tag | Meaning |
|---|---|
| **Approved** | Ojas Sharma approved this on 2026-10-04 as part of the Jira status mapping. |
| **Recorded decision** | A decision Ojas Sharma stated in Jira comments on KAN-20 (comments 10108 and 10113, 2026-10-04). It is recorded here; it is not an acceptance of this ADR. |
| **Proposed** | Proposal by the Architect agent. Not accepted. Marked **PROPOSED ASSUMPTION - REQUIRES HUMAN APPROVAL** where it goes beyond a source document or a decision. |
| **LR 04-proposed** | Proposal by the Backend agent. Not accepted. Also **PROPOSED ASSUMPTION - REQUIRES HUMAN APPROVAL**. |

## Context

Doc 17 s10 and s14 require a traceable chain Jira issue -> branch -> pull request -> CI/security/QA -> release, with stable ids. KAN-20 covers branch naming, PR links, CI status and issue transitions; bidirectional workforce synchronization is out of scope (KAN-26).

The live Jira project `KAN` is team-managed with four statuses, To Do, In Progress, In Review and Done (ADR-0001). It cannot enforce the doc 17 s4 workflow, so every rule below is held by convention, review and detection, not by Jira. Doc 17 s8/s9 and doc 16 s6 mention REWORK, but no Jira status of that name exists. Doc 17 s9 proposes automation (PR opened -> In Review; CI fails -> REWORK; security blocker -> BLOCKED; QA passes -> ready for release; deployment -> released; smoke test and acceptance -> Done); doc 17 s11 warns against moving tickets automatically without evidence.

Branch protection is unavailable (private repository, no plan upgrade), so no CI check can be a required merge gate technically; Ojas Sharma reviews and merges every pull request. Agents currently write to Jira and push to GitHub through the repository owner's accounts, so neither Jira authorship nor the Git author identifies which agent acted (see Security Impact).

## Problem

Record the decisions already taken, and define the status mapping and transition rules between the four Jira statuses and the engineering-workforce task lifecycle (doc 16 s6), so that branch names are checkable, rework is representable without a REWORK status, Done is reachable only through review and acceptance, and nothing automated can declare approval, release or acceptance.

## Options

1. **A. Decision basis as recorded, with a thin convention layer (chosen as the proposal).** Adopt the recorded and approved decisions. Add a mapping between the Jira work-item status and the workforce task lifecycle; evidence-bearing manual or agent-run transitions now, with automation later (KAN-26) limited to an allowlist that excludes Done; an advisory branch-name check in CI; Done only from In Review after required review and acceptance evidence.
2. **B. Mirror the runtime lifecycle in Jira labels** (many `exec-*` labels). Rejected: labels are free text and unreliable (ADR-0001), and no such labels were decided.
3. **C. Let Jira status drive the runtime** (workflow automation moves tickets on PR/CI events, including Done). Rejected: contradicts doc 17 s11 and the Done rules in point 15.
4. **D. Keep the earlier interim convention** (`feat|feature|...` prefixes, optional Jira key). Rejected: superseded by the recorded branch-naming decision.
5. **E. Wait for a Jira project with a real workflow.** Not available now (ADR-0001 exit criteria); revisit later.

## Decision

Option A. Each point carries its tag.

### Decision basis

| # | Decision | Tag | Source |
|---|---|---|---|
| D1 (C-04) | Branch names are `feature/KAN-<key>-description`, `bugfix/...`, `security/...`, `chore/...`, `docs/...`. | Recorded decision | KAN-20 comments 10108, 10113 |
| D2 (C-07) | REWORK is represented by Jira status **In Progress** plus label **`exec-rework`**, because the Jira workflow has no REWORK status. | Recorded decision; also part of the **Approved** mapping (D7) | KAN-20 comments 10108, 10113; status-mapping approval 2026-10-04 |
| D3 | The label `exec-rework` is removed when rework is complete. | Recorded decision | KAN-20 comment 10108 |
| D4 | KAN-20 -> KAN-19 is the correct dependency direction: Jira/Git integration establishes branch/PR/CI linkage first. | Recorded decision | KAN-20 comments 10108, 10113 |
| D5 | KAN-20 may start implementation. | Recorded decision | KAN-20 comment 10108 |
| D6 | **Approved (2026-10-04).** The statuses are To Do, In Progress, In Review, Done. New work starts in To Do; active implementation is In Progress; completed implementation goes to In Review; Done is reached only after required review and acceptance evidence. **Done is reachable only from In Review.** An earlier statement that a human can move any status directly to Done is superseded. A human may approve completion, but the issue must still satisfy the transition and acceptance rules. Agents never mark their own work Done. Completion of sensitive and release-critical work needs human approval. | **Approved** | status-mapping approval, Ojas Sharma, 2026-10-04 |
| D7 | **Approved (2026-10-04).** Rework lifecycle: In Review -> REWORK REQUIRED -> In Progress (label `exec-rework` + comment with an explicit reason) -> fix -> In Review -> review -> Done. Rework is never sent directly to Done and is never read as completed work. Rework-complete returns the work to In Review. REWORK REQUIRED is not a Jira status; it is represented by In Progress + `exec-rework` + the reason comment. BLOCKED is likewise not a status. | **Approved** | same |
| D8 | **Approved (2026-10-04).** In the transition matrix `human` is an actor for rework-complete and `owner_agent` is an actor for send-to-rework; no row lets anything other than In Review reach Done. | **Approved** | same |

### Points

1. **Branch form.** (Recorded decision D1.) `<type>/KAN-<key>-<description>` with `<type>` one of `feature`, `bugfix`, `security`, `chore`, `docs`. Reading `<key>` as the numeric part of the Jira key (so `KAN-20`, not `KAN-KAN-20`) is **PROPOSED ASSUMPTION - REQUIRES HUMAN APPROVAL**.
2. **REWORK representation.** (Recorded decision D2; **Approved**.) Jira status In Progress plus label `exec-rework`.
3. **Label removal.** (Recorded decision D3; **Approved** with D7.) `exec-rework` is removed when rework is complete, and the issue then returns to In Review, never directly to Done.
4. **Direction.** (Recorded decision D4.) KAN-20 -> KAN-19 stays. Merged work counts as partial progress on KAN-19 only.
5. **Start.** (Recorded decision D5.) KAN-20 may start. The general implementation hold on other issues is not changed by this ADR.
6. **Description format.** (Proposed.) `<description>` is lowercase kebab case, characters `a-z`, `0-9` and single hyphens, no leading or trailing hyphen; maximum branch-name length 100 characters; exactly one Jira key per branch. Reference regex: `^(feature|bugfix|security|chore|docs)/KAN-[1-9][0-9]*-[a-z0-9]+(-[a-z0-9]+)*$` plus the length rule. The prefix `feat` and the earlier optional-key rule end with this ADR. All of point 6 is **PROPOSED ASSUMPTION - REQUIRES HUMAN APPROVAL**.
7. **Existing branches.** (Proposed.) Branches that do not match are grandfathered: the check applies to pull requests opened after it exists and no history is rewritten.
8. **REWORK convention in full.** The lifecycle, status and label are **Approved** (point 16). When work returns for rework ("REWORK REQUIRED"), the issue goes from In Review to In Progress, label `exec-rework` is added and a Jira comment gives an explicit reason (D7). The comment should also carry the evidence link (failed check URL, review URL) and what completes the rework; that content is **PROPOSED ASSUMPTION - REQUIRES HUMAN APPROVAL** (only "explicit reason" is decided). Rework is "complete" when the corrected PR has passing checks and review is re-requested; the issue then returns to **In Review** and the label is removed (the return to In Review and the label removal are **Approved**; the exact completion trigger is **PROPOSED ASSUMPTION - REQUIRES HUMAN APPROVAL**). *LR 04-proposed:* every Jira comment about rework, and every other comment format in `docs/jira-comment-label-conventions.md`, also carries `by: <agent or person>`, because agents write to Jira through the owner's account and would otherwise look like the owner (security review finding F-5); `by:` is attribution by statement and is not authenticated. Evidence in a comment is a link (run, review or PR URL), never pasted log or command output, which can contain secrets. Both rules are **PROPOSED ASSUMPTION - REQUIRES HUMAN APPROVAL**.
9. **Two models, kept separate.** (Proposed.) The Jira status is the work-item view. The workforce task lifecycle (doc 16 s6) is the runtime view and, once the workforce runtime exists (KAN-21), its system of record. The customer incident state machine (doc 18 s8) is a third, unrelated model and is never mapped to Jira.
10. **Mapping.** The four-status model is **Approved**; the row-by-row mapping below is **Proposed** except where the Note says otherwise.

| Workforce task lifecycle (doc 16 s6) | Doc 17 s4 state | Jira status (ADR-0001) | Marker | Note |
|---|---|---|---|---|
| REGISTERED | BACKLOG | To Do | none | BACKLOG and READY are merged in KAN (ADR-0001) |
| READY | READY | To Do | none | live issues carry labels such as `exec-ready`; their semantics are not defined in ADR-0001 |
| CLAIMED | IN PROGRESS | In Progress | none | claim = owner starts work |
| EXECUTING | IN PROGRESS | In Progress | none | |
| VALIDATING | IN VALIDATION | In Review if a PR exists, otherwise In Progress | none | KAN has no validation status (ADR-0001) |
| REVIEW_REQUIRED | IN REVIEW | In Review | PR link comment | |
| REWORK ("REWORK REQUIRED") | (not in doc 17 s4) | In Progress, entered from In Review | label `exec-rework` + comment with explicit reason | **Approved** (D2, D7); no Jira status of that name exists |
| BLOCKED | BLOCKED | status unchanged | comment `BLOCKED: by: <who>; reason: <one line>` | BLOCKED is a comment, never a status (the approved model has four statuses); no label is defined; the `by:` field is LR 04-proposed |
| FAILED | (none) | In Progress | comment with failure evidence | Proposed |
| APPROVED | READY FOR RELEASE | In Review (unchanged) | review/approval evidence comment by the approver | not Done; Jira has no approved status; Done is a separate step from In Review (point 15) |
| RELEASED | RELEASED | unchanged (no release exists) | none | a release record is not a Jira transition |
| (acceptance confirmed) | DONE | Done, reached only from In Review | none | **Approved** (D6): after required review and acceptance evidence; never set by the owner agent for its own work; human approval for sensitive and release-critical work |

11. **Transition rules.** Actors: `owner_agent` (the agent that owns the issue/PR), `reviewer_agent` (reviewer, QA or security gate agent acting manually), `human` (Ojas or another authorized person), `automation` (webhook, CI step, adapter; none exists yet). Rows T3, T4, T5 and T6 implement D6-D8; T2 is Approved for the rule "completed implementation goes to In Review". Everything else is Proposed.

| # | Transition | Who | May automation do it? | Evidence required | Tag |
|---|---|---|---|---|---|
| T1 | To Do -> In Progress | owner_agent or human | yes, once an adapter exists (KAN-26); until then manual | claim record or first branch | Proposed |
| T2 | In Progress -> In Review (implementation completed) | owner_agent, human, or automation | yes | PR link (URL in a comment) and valid branch name | Rule **Approved**; actors and evidence Proposed |
| T3 | In Review -> In Progress = **send to rework** ("REWORK REQUIRED"): add label `exec-rework` + comment with an explicit reason | reviewer_agent, owner_agent, human, or automation on failed checks | yes | explicit reason in the comment; failed check or review URL (proposed); `by:` actor field in the comment (LR 04-proposed, point 8) | Path and actors (including `owner_agent`) **Approved**; evidence Proposed |
| T4 | In Progress (`exec-rework`) -> **In Review** = **rework complete**; label `exec-rework` removed | owner_agent, human, or automation | yes | corrected PR with passing checks, review re-requested | Target In Review and actors (including `human`) **Approved**; evidence Proposed |
| T5 | In Review -> **Done** | human (agents never for their own work) | **never** | required review done and acceptance criteria verified (doc 17 s7), evidence recorded; human approval for sensitive and release-critical work. *LR 04-proposed* evidence set, implemented in `scripts/jira-transition-allowlist.json` (field names are **PROPOSED ASSUMPTION - REQUIRES HUMAN APPROVAL**): validation/CI result link, required-review approval link, acceptance criteria verified (true) and who verified, merged PR link, a release reference or an explicit "no release required", an explicit sensitive-work flag (and a human-approval reference when it is true). A human cannot skip any of it. Denied while label `exec-rework` is present (T6) | Only-from-In-Review, required review and acceptance evidence, no agent self-Done and human approval for sensitive/release-critical work: **Approved**. That a human performs the transition, and the evidence field names: Proposed |
| T6 | To Do -> Done, In Progress -> Done, In Progress (`exec-rework`) -> Done | nobody | never | - | **Approved**: Done is reachable only from In Review; rework never goes directly to Done |
| T6a | In Review with label `exec-rework` still present -> Done | nobody | never | - | LR 04-proposed (**PROPOSED ASSUMPTION - REQUIRES HUMAN APPROVAL**): rework is never read as completed work |
| T7 | In Progress -> To Do, In Review -> To Do (return to backlog) | human | no | reason | Proposed |
| T8 | Done -> To Do / In Progress / In Review (reopen) | human | never | reason; a reopen into In Progress that keeps `exec-rework` needs a valid rework comment | Proposed |

   Any transition not listed in T1-T8 is not defined by this ADR. There is no row that lets a status other than In Review reach Done.

12. **No automated approvals.** (Proposed.) No automation (webhook, CI step, scheduled job, adapter, script) may transition an issue to Done, and none may write a label, field or comment that asserts an approval, a release or acceptance. Approvals and acceptance are written by the approving human or by a reviewer/gate agent acting manually, never by automation on its own authority. Jira cannot enforce this (ADR-0001), so enforcement is (a) a hard-coded transition allowlist in any integration code (KAN-26, KAN-27); the reference allowlist and its pure-logic checker are `scripts/jira-transition-allowlist.json` and `scripts/check_transition.py` in this repository, merged to `main` (PR #5) and tested to deny every agent or automation path to Done and every source status other than In Review (LR 04-proposed reference); (b) least-privilege credentials; (c) a detection check by JQL/changelog (see Operational Impact). The ADR-0001 mitigation wording "Humans or reviewer agents confirm DONE" is **not** adopted for performing the Done transition: T5 keeps the transition with a human (**PROPOSED ASSUMPTION - REQUIRES HUMAN APPROVAL**), while D6 independently forbids an agent from marking its own work Done.
13. **CI check.** (Proposed.) A job added by the infrastructure agent (LR 10) validates the pull-request head branch name against points 1 and 6. Because branch protection is unavailable, the check is advisory: Ojas Sharma reviews every PR and must treat a red branch-name check as a blocker by process. The CI job does not call Jira and holds no Jira credential. *LR 04-proposed invocation rules* (security review findings F-1, F-2, F-3; owner hold on PR #4, 2026-10-04): the job passes the head ref only through `env: BRANCH_NAME: ${{ github.head_ref }}` and runs `python3 scripts/check-branch-name.py` with NO arguments. The script reads only the fixed variable `BRANCH_NAME`, parses no options, refuses any argument (including `-h` and `--help`) with exit 2, never expands or evaluates the name, and prints it only escaped and truncated to 120 characters. Exit codes: 0 valid, 1 invalid (empty included), 2 variable not set or argument given; the step must treat ANY non-zero exit code as failure. `github.head_ref` is empty on push events, which is invalid (fail closed), so the job runs on `pull_request` only. These invocation rules are **PROPOSED ASSUMPTION - REQUIRES HUMAN APPROVAL**.
14. **Linkage.** (Proposed.) Jira key in the branch (point 1), in the PR template fields "Jira issue" and "Authoring agent" (*LR 04-proposed*: attribution by statement, not authenticated; agents push through the owner's account until separate identities exist, security review finding F-4), and in commit messages where practical; the PR URL is placed in the Jira issue (comment or remote link); CI status is referenced by link. Whether a GitHub-for-Jira integration app is installed is **not decided** (requires an administrator and human approval; plan and price UNKNOWN).
15. **Status model and Done rule.** (**Approved**, D6.) Statuses: To Do, In Progress, In Review, Done. New work starts in To Do; active implementation is In Progress; completed implementation goes to In Review; Done is reached only after required review and acceptance evidence and **only from In Review**. A human may approve completion, but the issue must still satisfy T5: human approval does not bypass In Review. Agents never mark their own work Done. Completion of sensitive and release-critical work needs human approval.
16. **Rework lifecycle.** (**Approved**, D7, D8.) In Review -> REWORK REQUIRED -> In Progress (label `exec-rework` + comment with an explicit reason) -> fix -> In Review -> review -> Done. "REWORK REQUIRED" is a lifecycle name, not a Jira status: it is represented by In Progress + `exec-rework` + the reason comment, applied in the single Jira transition In Review -> In Progress (T3). Rework is never sent directly to Done and is never read as completed work. Rework-complete (T4) returns the issue to In Review and removes the label; review then decides (T5).

## Rationale

- Separating the Jira work-item view from the workforce lifecycle keeps Jira's four statuses usable without inventing statuses or labels (ADR-0001 limits).
- Making In Review the only door to Done puts required review and acceptance evidence on the path of every completion, including a human's, and removes the earlier any-status shortcut.
- A hard-coded allowlist plus detection is the strongest control available while Jira cannot enforce workflow; it also gives KAN-26 and KAN-27 one rule set to import.
- Evidence as links and a `by:` field keep comments useful without pasting secrets and without pretending Jira authorship identifies the agent.

## Consequences

- Branch names are machine-checkable and Jira keys appear in every new branch, making the doc 17 s10/s14 chain traceable.
- `CONTRIBUTING.md` and the PR template must state the five-prefix rule (they do on `main` after PR #3).
- REWORK is visible with JQL `project = KAN AND labels = exec-rework`. The check `labels = exec-rework AND status != "In Progress"` should return nothing, because the label is removed when the issue returns to In Review (T4).
- Jira cannot enforce the rules; they are enforced by code allowlists, credential scoping, review and detection. A human or a credentialed account can still violate them (ADR-0001).
- Done is reached only from In Review after required review and acceptance evidence, and never by the owner agent for its own work; the Done transition stays with a human, which is a human bottleneck for acceptance.
- The mapping lets KAN-21 and KAN-24 define the workforce task lifecycle without changing Jira.
- The ADR settles C-04 and C-07 only for KAN as configured; it does not resolve C-09 (types and workflow).

## Security Impact

- Branch names are attacker-controlled input in CI. The check passes the name through an environment variable and compares it with a fixed pattern; it never interpolates `${{ github.head_ref }}` into a shell command (script injection). Workflow permissions stay read-only (`contents: read`).
- The integration holds no Jira credential in CI. Any later Jira credential (KAN-26) is scoped to the KAN project, rotated and not shared between agents.
- Done, approval and release assertions by automation would let an agent self-approve; points 12 and 15 remove that path. Residual risk: Jira does not technically block a human or a credentialed account.
- **Identity.** Agents currently write to Jira, and push to GitHub, through the repository owner's accounts. Jira authorship and the Git author therefore do not show which agent acted, and this ADR does not claim that an author and a reviewer are technically separate identities. `by:` in comments and the "Authoring agent" field in the PR template are attribution by statement and are not authenticated. "Independent review" in this repository is a process requirement. Technically separate agent identities do not exist today; creating them is a separate proposal that is not accepted.
- Jira text and PR text are untrusted input for any agent that reads them (prompt injection); a rework comment is data.
- Labels are free text: `exec-rework` can be added or removed by anyone with edit rights; never derive permissions from it.
- Evidence comments must not contain secrets, tokens or personal data; evidence is a link, not pasted output.

## Operational Impact

- Detection checks (manual or scheduled, read-only): (a) issues in Done whose changelog author is an integration or agent identity (attribution caveat above); (b) `labels = exec-rework` on issues whose status is not In Progress; (c) open PRs whose head branch fails the pattern; (d) issues in Done whose previous status was not In Review; (e) issues in Done whose Done transition was made by the owner agent's identity; (f) issues that went from In Progress with `exec-rework` straight to Done; (g) *LR 04-proposed*: `project = KAN AND status = Done AND labels = exec-rework` (rework must never be read as completed work).
- Transition events are logged as Jira comments and the Jira changelog; a central log is deferred until hosting and observability exist.
- KAN-20 asks for a test in a non-production Jira project; none exists. The implementation plan lists the options.
- CI cost: one short extra job within the GitHub Free allowance; exact usage UNKNOWN.
- Rollback: remove the CI job and revert the CONTRIBUTING/PR-template changes; no data migration.

## Alternatives Rejected

- B: invents labels and relies on free text.
- C: contradicts doc 17 s11 and the Done rules of point 15.
- D: conflicts with the recorded branch-naming decision.
- E: not available; revisit when Jira can be reconfigured (ADR-0001 exit criteria).

## Known inconsistencies and handling

| # | Finding | Severity | Handling |
|---|---|---|---|
| X1 | ADR number collision between the architect's and the security agent's drafts of ADR-0002 and ADR-0003. | M | Resolved by the ADR ledger ruling of 2026-10-04: the security drafts carry the provisional ids ADR-S01 and ADR-S02; final repository numbers are assigned when each ADR PR is opened. |
| X2 | ADR-0001 says C-07 (REWORK) is still open; the REWORK representation is now decided. | L | ADR-0001 is Accepted (interim) and is not rewritten by this ADR; see the amendment note proposed in the stale-text corrections. |
| X3 | ADR-0001 mitigation "Humans or reviewer agents confirm DONE" differs from D6 (Done only from In Review; agents never mark their own work Done) and from T5 (a human performs the Done transition: Proposed). | M | Flagged; ADR-0001 amendment note proposed. |
| X4 | An earlier security draft proposed agent branches `agent/<id>/*`; the recorded decision allows only the five prefixes. | L | Resolved: the five prefixes apply. |
| X5 | An earlier conflict proposal (C-04) recommended a union branch pattern; the recorded decision chose the Jira-key form and dropped `feat`. | L | Superseded by D1. |
| X6 | The illustrative C-10 mapping said BLOCKED could be a label or status; here BLOCKED is a comment only. | L | Consistent with the approved four-status model. |
| X7 | Doc 17 s9 automation (CI fails -> REWORK; QA pass -> ready for release; deployment -> released; smoke test -> Done) versus point 12 and D6. | M | Doc 17 s9 is the baseline; this ADR restricts it: no automatic Done, approval or release, and Done only from In Review; "CI fails -> REWORK" maps to T3. |
| X8 | Doc 17 s8: implementation bots cannot mark Done; QA/Security "transition to validation/rework". | L | Consistent. |
| X9 | Labels `exec-ready`, `exec-wave-1` and `decision-resolved` exist on live issues but are not in the ADR-0001 label scheme. | L | The scheme should list them; `exec-rework` joins them. |
| X10 | `CONTRIBUTING.md` and the PR template used the earlier branch convention. | M | Fixed on `main` by PR #3. |
| X11 | Existing branches (`chore/bootstrap-repository-baseline`, `docs/KAN-orchestration-agent-assignment-registry`) do not match the rule. | L | Grandfathered by point 7. |
| X14 | The "explicit Jira comment" requirement and D3 are stated in a single source each. | L | Treated as Proposed (point 8). |
| X16 | The earlier rule "a human may move any status to Done" (an `any -> Done` matrix row and related text) conflicted with D6. | H | Removed from this ADR; Done is reached only through T5. |
| X17 | An earlier matrix row read rework-complete as "In Review -> In Progress", contradicting point 8; actors `human` (rework-complete) and `owner_agent` (send-to-rework) were missing. | H | Fixed: T3 and T4; actors added (D8). |
| X18 | "REWORK REQUIRED" has no Jira status. | L | Represented by In Progress + `exec-rework` + reason comment (point 16); no status or label is invented. |
| X19 | ADR-0001 and some repository docs still carried pre-decision wording (C-07 open; "reviewer agents confirm DONE"; "separate agent identities"). | M | Corrections proposed separately as a patch; ADR-0001 gets an amendment note. |
| X20 | Identity-separation claims: the earlier PR-template checkbox and the CONTRIBUTING ground rule said author and reviewer are "different identities", but agents push through the owner's GitHub account (security review finding F-4). | M | LR 04-proposed. Fixed on `main` by PR #3: the wording is now "Independent review required before merge." and an "Authoring agent" field records attribution by statement. Remaining occurrences in `docs/workforce/agent-registry.md` are covered by the proposed stale-text corrections. |

## History

| Date | Change |
|---|---|
| 2026-10-04 | Proposed by the Architect agent for KAN-20 (decision basis D1-D5 from KAN-20 comments 10108 and 10113). |
| 2026-10-04 | Updated for the status-mapping approval by Ojas Sharma (D6-D8, points 15-16, matrix T1-T8, BLOCKED as comment only). |
| 2026-10-04 | Finalized as repository text: template sections, tags per section, LR 04-proposed additions (`by:`, link-only evidence, acceptance-evidence set, T6a, allowlist reference, PR #4 invocation rules, "Authoring agent", detection check (g), X20), identity wording made truthful. Provisional number: ADR-0017, subject to the ADR ledger ruling (final number assigned when the PR is opened). |
