# LifeRescue — Start Here Bootstrap Guide

## Goal

Do not start by building the UI.

Start by establishing the engineering control system so the 24x7 AI workforce can build the product safely.

## Step 1 — Create Accounts/Infrastructure

Create or confirm:

1. GitHub or Bitbucket repository
2. Jira project
3. Confluence space
4. Nebius account/project
5. NVIDIA/Nemotron model access through the required Nebius path
6. xAI/Grok access for the engineering workforce
7. Tavily API key
8. container registry
9. cloud/environment accounts as required

Keep customer inference and engineering automation logically separated.

## Step 2 — Create the Repository

Create:

```text
liferescue/
  apps/
  services/
  packages/
  agents/
  tools/
  infrastructure/
  tests/
  docs/
  scripts/
```

Add README, LICENSE, CONTRIBUTING, SECURITY, CODEOWNERS and repository rules.

## Step 3 — Protect Main

Configure:

- pull requests required
- minimum reviewer requirement
- status checks required
- force push disabled
- deletion disabled
- secrets scanning
- dependency alerts
- signed commits/commits where practical

No agent receives direct main-branch write access.

## Step 4 — Create Jira Project

Project key:

`LR`

Create issue types:

- Initiative
- Epic
- Story
- Task
- Bug
- Spike
- Security
- Incident
- Change

Create the workflow from the Jira operating model.

## Step 5 — Create Initial Epics

Create:

1. LR-EPIC-01 Product Foundation
2. LR-EPIC-02 Engineering Workforce
3. LR-EPIC-03 Incident Core
4. LR-EPIC-04 Agent Runtime
5. LR-EPIC-05 Tool Gateway
6. LR-EPIC-06 Vehicle Breakdown Workflow
7. LR-EPIC-07 Security & Trust
8. LR-EPIC-08 Observability
9. LR-EPIC-09 Infrastructure & Deployment
10. LR-EPIC-10 Hackathon Release

Do not manually invent issue IDs; Jira generates them.

## Step 6 — Create the First Tasks

Create these first:

### LR-1 Product Constitution
Acceptance:
- product mission approved
- non-goals documented
- target users documented
- safety principles documented

### LR-2 Architecture Baseline
Acceptance:
- architecture diagram
- service boundaries
- ADR index
- technology decisions

### LR-3 Repository Bootstrap
Acceptance:
- repository structure
- local development
- formatting/lint/typecheck
- initial CI

### LR-4 Jira/Git Integration
Acceptance:
- branch naming
- PR links
- CI status
- issue transitions

### LR-5 Agent Workforce Runtime
Acceptance:
- bot registry
- task contract
- execution lifecycle
- audit events

### LR-6 Security Baseline
Acceptance:
- threat model
- secret management
- dependency scanning
- security CI

## Step 7 — Bootstrap the Workforce

Start with only five bots:

1. Product Bot
2. Architect Bot
3. Backend Bot
4. QA Bot
5. Security Bot

Do not start all 13 simultaneously.

The first bots should prove the operating model.

## Step 8 — Create the First Agent Task

Give the Architect Bot:

> Review the LifeRescue repository and documentation. Produce the architecture baseline, identify contradictions, create ADR proposals, and create Jira tasks for missing foundations. Do not implement code. Do not modify production configuration. Return structured results.

The result should become:
- Jira issues
- ADRs
- architecture updates
- risk list

## Step 9 — Implement CI Before Feature Development

Minimum pipeline:

```text
Checkout
 -> Dependency install
 -> Format check
 -> Lint
 -> Type check
 -> Unit tests
 -> Integration tests
 -> Security scan
 -> Secret scan
 -> Build
 -> Artifact
```

A failed pipeline must block release.

## Step 10 — Implement the Agent Runtime

Build:

- Bot Registry
- Task Queue
- Task Runner
- Tool Registry
- Policy Engine
- Audit Log
- Agent Run Store
- Result Validator
- Retry/Timeout Controller

Only then allow coding bots to operate autonomously.

## Step 11 — Connect Jira

The workforce should be able to:

```text
Jira issue
 -> claim task
 -> create branch
 -> implement
 -> run tests
 -> open PR
 -> update Jira
 -> wait for review
 -> rework if needed
 -> release when approved
```

The Atlassian integration can later provide direct Jira/Confluence/Bitbucket operations.

## Step 12 — Build the Customer Product

Build in this order:

1. identity
2. incident creation
3. incident state machine
4. evidence
5. policy
6. approval
7. agent runtime
8. tool gateway
9. verification
10. vehicle breakdown workflow
11. notifications
12. UI refinement

## Step 13 — Add Real Integrations

Only after the simulated workflow is stable:

- maps/location
- assistance providers
- communication
- research
- external status verification

Every integration gets:
- contract
- sandbox/mock
- timeout
- retry
- audit
- security review
- failure simulation

## Step 14 — Production Hardening

Before calling it production-ready:

- load tests
- failure injection
- prompt injection tests
- authorization tests
- privacy review
- dependency audit
- backup restoration test
- rollback test
- observability review
- cost review
- incident response drill

## Step 15 — Hackathon Packaging

Only after the product is coherent:

- deploy public demo
- publish repository
- finalize architecture
- prepare test scenarios
- prepare short demo script
- document Nebius/NVIDIA usage
- document Tavily runtime usage
- capture measurable results
- prepare final submission

## Golden Rule

Do not ask:

> What can the AI build next?

Ask:

> What is the next verified product capability required by the roadmap, and what evidence proves it is complete?

That keeps the autonomous workforce aligned with the product rather than letting it generate uncontrolled code.
