# LifeRescue — Jira Engineering Operating Model v0.2

## 1. Objective

Jira is the work-management system of record for product delivery.

It does not replace:
- Git as source of code
- CI as source of verification
- runtime telemetry as source of operational truth
- ADRs as source of architectural decisions

## 2. Recommended Hierarchy

```text
Jira Project: LR
  Initiative
    Epic
      Story / Task
        Sub-task
```

Use Components for system ownership and Labels sparingly.

Recommended components:
- product
- web
- api
- domain
- agents
- tools
- security
- infrastructure
- observability
- data
- integrations
- documentation
- hackathon

## 3. Issue Types

### Initiative
Large business outcome.

Examples:
- Incident Coordination Platform
- Engineering Workforce
- Production Readiness

### Epic
A major independently trackable capability.

Examples:
- Incident Core
- Agent Runtime
- Vehicle Breakdown Workflow
- Tool Gateway
- Security Platform

### Story
User-visible or business-value behavior.

### Task
Engineering or operational work.

### Bug
Observed incorrect behavior.

### Spike
Time-boxed investigation.

### Security
Security-specific work or vulnerability.

### Incident
Production operational incident.

### Change
Controlled infrastructure/production change.

## 4. Workflow

```text
BACKLOG
 -> READY
 -> IN PROGRESS
 -> IN REVIEW
 -> IN VALIDATION
 -> READY FOR RELEASE
 -> RELEASED
 -> DONE
```

Exception states:

```text
BLOCKED
REJECTED
CANCELLED
```

### State rules

BACKLOG:
Not yet refined.

READY:
Acceptance criteria, owner, dependencies and scope exist.

IN PROGRESS:
One accountable owner/agent is actively implementing.

IN REVIEW:
PR exists and automated checks are available.

IN VALIDATION:
QA/security/evaluation checks are running.

READY FOR RELEASE:
All required gates passed.

RELEASED:
Deployed to target environment and smoke checks passed.

DONE:
Acceptance criteria confirmed and documentation synchronized.

## 5. Required Fields

Every implementation issue should contain:

- objective
- business value
- acceptance criteria
- non-goals
- dependencies
- security considerations
- observability requirements
- test requirements
- target release
- component
- owner
- reviewer
- linked PR
- linked ADR where applicable

## 6. Definition of Ready

An issue can move to READY only when:

- objective is clear
- scope is bounded
- acceptance criteria are testable
- dependencies are identified
- required design is available
- security impact is understood
- owner is assigned

## 7. Definition of Done

An issue can move to DONE only when:

- implementation merged
- CI passed
- required tests passed
- security checks completed
- observability added
- documentation updated
- acceptance criteria verified
- deployment status known
- Jira links synchronized

## 8. Agent Jira Permissions

### Product Bot
Can:
- create issues
- edit requirements
- change backlog metadata

Cannot:
- close implementation issues

### Implementation Bots
Can:
- claim assigned tasks
- update progress
- attach PRs
- add technical comments

Cannot:
- mark DONE
- approve own work

### QA/Security
Can:
- add findings
- transition to validation/rework
- approve their specific gate

### Release Manager
Can:
- move release-ready issues
- record release results

### Human Owner
Can:
- approve sensitive transitions
- override automation with audit reason

## 9. Automation Rules

### PR opened
Jira issue -> IN REVIEW.

### CI passes
Issue receives verification event.

### CI fails
Issue -> REWORK and failure details are attached.

### Security blocker
Issue -> BLOCKED.

### QA passes
Issue -> READY FOR RELEASE.

### Deployment succeeds
Issue -> RELEASED.

### Smoke test succeeds and acceptance is verified
Issue -> DONE.

## 10. Task Synchronization

Use stable IDs:

```text
Jira: LR-123
Branch: feat/LR-123-incident-create
PR: #456
Commit: linked
CI run: linked
Agent run: AR-789
```

This creates end-to-end traceability.

## 11. Sprint/Cadence

For autonomous engineering:

- 1-week delivery cycle
- daily automated status refresh
- human product review at least weekly
- release train based on readiness, not arbitrary calendar pressure

Avoid creating fake progress by moving tickets automatically without evidence.

## 12. Dashboards

### Executive/Product
- epics completed
- release progress
- blocked work
- critical risks
- customer workflow coverage

### Engineering
- throughput
- cycle time
- PR age
- CI success rate
- rework
- defect escape

### AI Workforce
- tasks completed
- first-pass success
- intervention rate
- cost per task
- token usage
- average tool calls
- blocked tasks
- security findings

### Release
- open blockers
- test pass rate
- security status
- deployment health
- rollback readiness

## 13. Confluence

Use Confluence for:
- product requirements
- architecture
- ADR index
- operational runbooks
- security documentation
- release documentation

Git Markdown remains the engineering source of truth for versioned code-adjacent documentation.

## 14. Jira + Git + CI Contract

```text
Jira
  | issue ID
  v
Git branch
  |
  v
Pull Request
  |
  +--> CI
  +--> Security
  +--> QA
  |
  v
Release
  |
  v
Observability
```

Every production change should be traceable through this chain.

## 15. Alternative: Linear

Linear is acceptable for a smaller team, but for this project Jira + Confluence + Bitbucket/GitHub provides a stronger enterprise-style operating model and integrates naturally with the governance model above.

