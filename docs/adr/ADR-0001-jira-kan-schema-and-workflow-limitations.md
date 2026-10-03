# ADR-0001: Jira project KAN schema and workflow limitations

- Status: Accepted (interim)
- Date: 2026-10-03
- Deciders: Ojas Sharma (decision owner). Drafted by Grok Bot (documentation executor) for Ojas Sharma; agents may propose, not accept.
- Jira: project KAN, backlog KAN-4 to KAN-55 (52 items). Most relevant items: KAN-20 (T-4 Jira/Git Integration), KAN-26 (S-04 Jira API adapter and synchronization), KAN-23 (S-01 Resolve documentation gaps and conflicts register).
- Confluence: page 196722 "ADR-0001 Jira KAN schema and workflow limitations" (matching page under the LifeRescue root, space SD, https://liferescue.atlassian.net/wiki/spaces/SD/pages/196722) (matching page under the LifeRescue root, space SD); Backlog Draft page 425986; Open Decisions and Conflicts page 229681 (conflicts C-01, C-07, C-09).
- Revisit when: a Jira project with key `LR` is created (see Exit criteria).

## Context

The baseline documents require a Jira project with the key `LR` (doc 17 s2/s10, doc 19 s4), the issue types Initiative, Epic, Story, Task, Sub-task, Bug, Spike, Security, Incident and Change, a components list, and an 11-state workflow (doc 17 s3 and s4). Doc 17 s4 lists the states `BACKLOG`, `READY`, `IN PROGRESS`, `IN REVIEW`, `IN VALIDATION`, `READY FOR RELEASE`, `RELEASED`, `DONE` and the exception states `BLOCKED`, `REJECTED`, `CANCELLED`.

Observed on 2026-10-03 (read back from Jira via the Atlassian connector, namespace user-Atlassian, site https://liferescue.atlassian.net):

- Projects on the site: `KAN` (name "LifeRescue", id 10001, software, style next-gen = team-managed) and `SAM1` ("(Example) Billing System Dev"). No project with the key `LR` exists.
- Issue types available in KAN: Epic (10006), Subtask (10007), Task (10008), Story (10009). Four types in total.
- Statuses in KAN (`listJiraStatuses`, mode project): To Do (10004, category new), In Progress (10005), In Review (10006), Done (10007). All four statuses apply to all four issue types.
- Components in KAN: none (0).
- Issue link types on the site: Blocks (blocks / is blocked by), Cloners (clones / is cloned by), Duplicate (duplicates / is duplicated by), Relates (relates to / relates to).
- The Atlassian connector can create issues, links, comments, versions and sprints. It has no operation that creates a Jira project, issue type, status, workflow or workflow scheme. Those changes need a Jira administrator in the Jira UI.

Ojas Sharma decided on 2026-10-03: use KAN as is, map the missing issue types to labels, and record the gap (this ADR). The 52 backlog items were then created as KAN-4 to KAN-55 (52 of 52, read back by JQL; see `bootstrap/jira-creation-report.md`). The pre-existing samples KAN-1 to KAN-3 were not touched.

## Problem

The documented operating model cannot be implemented as written in KAN. This ADR records exactly where KAN differs from doc 17 and doc 19, how the gap is bridged for now, what it costs, and when the decision is revisited.

## Options

1. Create a project `LR` in the Jira UI (company-managed is recommended in conflict C-09), configure the doc 17 types, workflow, components and fields, then create or migrate the backlog there.
2. Adopt KAN and rewrite the documents (conflict C-01 option b).
3. Rename the key of KAN to `LR` in Jira administration (conflict C-01 option c).
4. Use KAN as is, map missing issue types, statuses and components to labels and conventions, and record the gap.

## Decision

Option 4. Decided by Ojas Sharma on 2026-10-03: "Use KAN as is, mapping missing types to labels and reporting the gap." Status of this ADR is "Accepted (interim)". It is revisited if an `LR` project is created. Options 1 to 3 stay open and are not rejected.

### Comparison: required versus actual

| Topic | Required by the baseline docs | Actual in KAN |
|---|---|---|
| Project key | `LR` (doc 17 s2/s10, doc 19 s4) | `KAN`. Key `LR` does not exist (C-01) |
| Project style | not stated for the project; company-managed is recommended in C-09 | team-managed (next-gen) |
| Issue types | Initiative, Epic, Story, Task, Sub-task, Bug, Spike, Security, Incident, Change | Epic, Story, Task, Subtask only |
| Workflow states | 11 (listed below) | 4 (listed below) |
| REWORK | referenced in doc 17 s8 and s9, absent from doc 17 s4 state list (C-07); present in doc 16 s6 task lifecycle | not a status |
| Components | doc 17 s2 component list | none exist |
| Hierarchy | Initiative > Epic > Story/Task | Initiative type missing; Epics cannot be parented under Epics |
| Required fields (doc 17 s5) | objective, acceptance criteria, owner, reviewer, and others | only summary, issue type, project and reporter are required by Jira; the rest is description convention |
| Issue link types | `blocks` dependencies | Blocks, Cloners, Duplicate, Relates |

### Workflow states: 11 required versus 4 available

Required by doc 17 s4 (11): `BACKLOG`, `READY`, `IN PROGRESS`, `IN REVIEW`, `IN VALIDATION`, `READY FOR RELEASE`, `RELEASED`, `DONE`, `BLOCKED`, `REJECTED`, `CANCELLED`.

Available in KAN (4): `To Do`, `In Progress`, `In Review`, `Done`.

Mapping used:

| Doc 17 state | KAN status |
|---|---|
| BACKLOG, READY | To Do (the two are merged; the BACKLOG versus READY distinction is not representable) |
| IN PROGRESS | In Progress |
| IN REVIEW | In Review |
| DONE | Done |
| IN VALIDATION, READY FOR RELEASE, RELEASED, BLOCKED, REJECTED, CANCELLED | no equivalent (7 states missing) |

### REWORK

REWORK is not a status in KAN. It is also absent from the state list in doc 17 s4, although doc 17 s8 ("transition to validation/rework") and s9 ("Issue -> REWORK") refer to it. This is the open conflict C-07. This ADR does not decide it. In KAN no REWORK state is used.

### Issue type mapping

| Doc 17 type | Representation in KAN |
|---|---|
| Initiative | Epic with label `type-initiative` and summary prefix "[Initiative] " (KAN-4, KAN-5, KAN-6) |
| Epic | Epic with label `type-epic` |
| Story | Story (KAN-33, KAN-43) |
| Task | Task |
| Spike | Task with label `type-spike` (KAN-50, KAN-53, KAN-54) |
| Bug, Security, Incident, Change | no draft item uses them; labels `type-bug`, `type-security`, `type-incident`, `type-change` are reserved and unused |

Initiatives are Epics related to their child Epics with "Relates" links (epic to initiative) plus an `init-i-N` label on the Epic, because Epics cannot be parented under Epics in KAN. There are 10 such links (KAN-7, 9, 10, 11, 12, 16 to KAN-4; KAN-8 to KAN-5; KAN-13, 14, 15 to KAN-6).

### Label scheme

| Label | Meaning |
|---|---|
| `type-initiative`, `type-epic`, `type-spike` | doc 17 issue type that KAN lacks, or Epic marker. `type-bug`, `type-security`, `type-incident`, `type-change` are reserved |
| `owner-lrNN-<role>` | owner agent, for example `owner-lr04-backend` |
| `reviewer-lrNN-<role>` | reviewer agent, for example `reviewer-lr03-architect` |
| `comp-<component>` | component from the doc 17 s2 list (KAN has no components), for example `comp-agents` |
| `draft-<id>` | draft ID from the Backlog Draft (for example `draft-s-02`, `draft-e-01`, `draft-i-1`) |
| `init-i-N` | parent initiative of an Epic (for example `init-i-1`) |
| `needs-pm-review` | derived acceptance criteria not yet reviewed by the Product Manager (33 items, S-01 to S-33) |

Initiatives and Epics carry no owner or reviewer labels because the draft does not assign them. Owner and reviewer are different agents on every item that has both (Backlog Draft rule).

## Rationale

- Key `LR` does not exist and the connector cannot create projects, issue types, statuses or workflows (verified by catalogue search and read-back on 2026-10-03).
- The owner approved using KAN as is. Labels and links are the only mapping mechanisms the connector offers inside a team-managed project.
- All facts above were read back from Jira on 2026-10-03.

## Consequences

- Workflow cannot enforce doc 17: no IN VALIDATION, READY FOR RELEASE, RELEASED, BLOCKED, REJECTED or CANCELLED state, and BACKLOG and READY are merged. Transitions between the four statuses are not gated, so doc 17 gate rules (for example implementation bots cannot mark DONE, doc 17 s8) hold by convention only.
- Labels are free text. A mistyped label is not rejected by Jira, and labels are not reliable as access control or as required fields.
- Doc 17 s5 required fields are not enforced by Jira. The 12 required headings live in the issue description.
- JQL filters must use labels (`labels = type-spike`, `labels = comp-agents`) instead of issue type or component fields. Dashboards and automation built on them depend on the label scheme staying consistent.
- Initiative rollup is not available as native hierarchy; it depends on "Relates" links and `init-i-N` labels.
- Issue keys are `KAN-n`, not `LR-n`. Docs, branch names (doc 17 s10 example `feat/LR-123-...`), PR references and the Jira-Git integration (KAN-20) must use the `KAN` key or be revised (conflict C-01). PR #1 in ojas005/liferescue was created before the key was fixed; its commit and branch names do not contain a Jira key.
- Remote links to Confluence cannot be removed through the connector (no operation); cleanup would need the Jira UI.
- Migration to an `LR` project later costs one move or recreate of 52 items plus links, with new keys.

## Mitigations

- Keep the label scheme above as the single convention and document it here and in Confluence page 425986 section 8.
- Run a periodic JQL check of the scheme, for example `project = KAN AND issuetype in (Task, Story) AND labels is EMPTY`, and compare counts to the Backlog Draft (52 items; 33 with `needs-pm-review`).
- Do not use automation that moves tickets without evidence (doc 17 s11). Humans or reviewer agents confirm DONE.
- Record status semantics for the merged and missing states in the issue description or a comment (for example "blocked: <reason>") until BLOCKED exists. This is a convention, not an enforced state.
- Do not reuse KAN-1 to KAN-3 (pre-existing samples).
- Treat all Jira-side configuration changes (project, types, workflow, fields) as human actions for a Jira administrator.

## Security Impact

- No application data or secrets are involved. The relevant risk is process integrity: without enforced states and required fields, a self-approval path (owner moving their own ticket to Done) is not technically blocked in KAN. Mitigation: human review before DONE, and an independent reviewer agent assigned per issue.
- Labels `owner-*` and `reviewer-*` are informational. Agent permissions are not derived from them.

## Operational Impact

- Reporting and dashboards use label-based JQL.
- Jira/Git integration (KAN-20) and the Jira API adapter (KAN-26) must target KAN and the 4 statuses until a different project exists.
- No cost impact is recorded.

## Alternatives Rejected

None rejected. Options 1 to 3 remain available and are the path described in the exit criteria. Option 4 was chosen as the interim approach by the owner.

## Exit criteria (when to migrate to LR)

Revisit this ADR, and plan the migration, when any of the following is true:

1. A Jira administrator creates a project with key `LR`, with the doc 17 issue types (Initiative, Epic, Story, Task, Bug, Spike, Security, Incident, Change), the 11-state workflow, components and required fields.
2. The owner decides conflict C-07 (REWORK) and the final workflow state list is fixed.
3. Enforced gates (IN VALIDATION, READY FOR RELEASE, BLOCKED and so on) are needed before agents beyond Wave 1 are activated, or before any production or release step.
4. Branch naming and Jira-Git integration (KAN-20, conflict C-04) are implemented and need the final key.

Migration steps (outline, not performed): verify types and workflow in `LR`; create or move the 52 items; recreate Blocks and Relates links (convert initiative Relates links to hierarchy); replace labels `type-*`, `comp-*` with native types and components; update Confluence "Related Jira" rows and this ADR (status "Superseded by ADR-NNNN" or amended); read back counts.

## Related Jira

- Project KAN; backlog KAN-4 to KAN-55 (draft IDs I-1..I-3, E-01..E-10, T-1..T-6, S-01..S-33). Initiatives KAN-4, KAN-5, KAN-6; Epics KAN-7 to KAN-16.
- KAN-20 (T-4 Jira/Git Integration), KAN-26 (S-04 Jira API adapter and synchronization), KAN-23 (S-01 documentation gaps and conflicts register).
- Report: `bootstrap/jira-creation-report.md` (outside this repository, in the bootstrap workspace).

## Related Confluence

- Jira Backlog Draft (page 425986), section 8 mapping table.
- Open Decisions and Conflicts (page 229681): C-01 (project key, decided by Ojas Sharma 2026-10-03), C-07 (REWORK, still open), C-09 (types and workflow, still open).
- Jira Engineering Operating Model v0.2 (doc 17, page 196658); Start Here Bootstrap Guide (doc 19, page 229664).
- Numbering note: the Open Decisions page section D proposes an "ADR-002 Jira project key, issue types and workflow (incl. REWORK)". This record is ADR-0001 as requested by the owner and covers only the interim KAN decision; the REWORK and final workflow decisions remain open.
- File naming note: `docs/adr/README.md` suggests `NNNN-short-title.md`; this file uses `ADR-0001-...` as requested by the owner.
