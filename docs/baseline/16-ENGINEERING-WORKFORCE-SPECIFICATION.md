# LifeRescue — Engineering Workforce Specification v0.2

## 1. Purpose

Define the autonomous engineering workforce that builds, tests, secures, documents, operates, and releases LifeRescue.

The workforce is an engineering control system, not a collection of unrestricted coding agents.

Primary principle:

> Agents may propose and implement changes inside bounded authority; production authority remains governed by policy and human approval.

## 2. Workforce Architecture

```text
                    HUMAN CONTROL PLANE
                           |
                    Product / Approvals
                           |
                 WORKFORCE ORCHESTRATOR
                           |
        +------------------+------------------+
        |                  |                  |
     TASK QUEUE        BOT REGISTRY       MEMORY
        |                  |                  |
   +----+----+--------+----+----+--------+----+
   |         |        |         |        |    |
Product   Architect Backend  Frontend   QA Security
   |         |        |         |        |    |
   +---------+--------+---------+--------+----+
                           |
                      Git / PR / CI
                           |
                    Staging / Production
                           |
                    Observability Plane
```

## 3. Source of Truth Hierarchy

When sources conflict:

1. Security and policy constraints
2. Approved product requirements
3. Architecture decision records
4. API/data contracts
5. Automated tests and acceptance criteria
6. Jira task metadata
7. Agent-generated suggestions

Jira tracks work. Git tracks implementation. CI tracks verification. Runtime observability tracks deployed behavior. Documentation explains intent.

## 4. Bot Registry

Each bot must have:

- immutable bot ID
- role
- mission
- versioned system prompt
- allowed tools
- denied tools
- repository permissions
- Jira permissions
- model/provider
- context sources
- maximum task duration
- maximum tool calls
- token/cost budget
- retry policy
- escalation policy
- approval requirements
- output schema
- metrics
- audit policy

## 5. Initial Workforce

### Product Bot
Mission: convert business goals into measurable requirements.

Allowed:
- read requirements
- create/update Jira issues
- propose acceptance criteria
- propose release scope

Not allowed:
- merge code
- deploy
- modify security policy

### Product Manager Bot
Mission: maintain backlog quality, dependencies, priorities, and release readiness.

### Architect Bot
Mission: design service boundaries, ADRs, contracts, scalability and reliability decisions.

### Backend Bot
Mission: implement backend services, APIs, domain logic, persistence and tests.

### Frontend Bot
Mission: implement accessible, secure, tested user interfaces.

### Agent Engineer Bot
Mission: implement agent workflows, prompts, schemas, tool adapters, policy integration and evaluation.

### QA/Evaluation Bot
Mission: verify functional correctness, regression safety, agent behavior and acceptance criteria.

### Security Bot
Mission: identify vulnerabilities, unsafe dependencies, secret exposure, authorization failures and insecure agent/tool behavior.

### Red Team Bot
Mission: actively attempt prompt injection, tool abuse, authorization bypass, data leakage, fabricated success and other adversarial behaviors.

### SRE/DevOps Bot
Mission: infrastructure, deployment, observability, reliability, backups, recovery and operational automation.

### Code Reviewer Bot
Mission: independently review implementation against requirements, architecture and engineering standards.

### Documentation Bot
Mission: keep ADRs, API documentation, runbooks, diagrams and release notes synchronized with implementation.

### Release Manager Bot
Mission: verify release gates, produce release candidates, coordinate approvals and execute governed releases.

## 6. Bot Lifecycle

```text
REGISTERED
  -> READY
  -> CLAIMED
  -> EXECUTING
  -> VALIDATING
  -> REVIEW_REQUIRED
  -> APPROVED
  -> RELEASED

Failure:
EXECUTING -> BLOCKED
EXECUTING -> FAILED
VALIDATING -> REWORK
REVIEW_REQUIRED -> REWORK
```

No bot may silently change a task from blocked to completed.

## 7. Task Contract

Every bot receives a machine-readable task:

```json
{
  "taskId": "LR-123",
  "type": "implementation",
  "objective": "Implement incident creation endpoint",
  "priority": "high",
  "requirements": [],
  "acceptanceCriteria": [],
  "constraints": [],
  "sourceOfTruth": [],
  "allowedFiles": [],
  "allowedTools": [],
  "maxSteps": 30,
  "timeoutSeconds": 1800,
  "budget": {
    "maxTokens": 50000,
    "maxUsd": 5
  },
  "requiredChecks": [
    "format",
    "lint",
    "typecheck",
    "unit",
    "integration",
    "security"
  ]
}
```

## 8. Bot Result Contract

```json
{
  "taskId": "LR-123",
  "status": "completed",
  "summary": "...",
  "filesChanged": [],
  "testsRun": [],
  "testsPassed": [],
  "testsFailed": [],
  "securityFindings": [],
  "architectureChanges": [],
  "risks": [],
  "followUp": []
}
```

## 9. Execution Rules

Each implementation task gets:

- isolated branch/worktree
- least-privilege credentials
- task-scoped filesystem permissions
- task-scoped Jira access
- bounded tool calls
- bounded runtime
- immutable execution log
- reproducible CI environment

Agents must not:
- push directly to protected main
- disable CI checks
- modify branch protection
- retrieve production secrets
- approve their own changes
- merge their own PR
- deploy to production without release policy approval

## 10. Bot-to-Bot Collaboration

Bots communicate through durable artifacts:

- Jira issue
- Git branch
- pull request
- CI result
- test report
- security report
- ADR
- release candidate
- structured task result

Avoid conversational hidden state as the source of truth.

## 11. Independent Review

The implementation bot and reviewer bot must be separate agent identities.

Recommended chain:

```text
Requirement
 -> Implementation Bot
 -> CI
 -> Security Bot
 -> QA Bot
 -> Independent Reviewer
 -> Human approval where required
 -> Release Bot
```

The reviewer must not inherit the implementation bot's private reasoning.

## 12. Continuous Workforce

### Event driven
- Jira issue created
- Jira status changed
- pull request opened
- pull request updated
- CI failed
- deployment failed
- production incident created

### Scheduled
- hourly repository health
- daily dependency/security review
- daily documentation drift
- daily flaky-test analysis
- daily cost anomaly review
- daily agent evaluation regression
- weekly architecture review
- weekly backlog hygiene

Agents may observe continuously, but continuous autonomous production mutation is prohibited.

## 13. Stop Conditions

A bot must stop and escalate when:

- requirements conflict
- required permission is unavailable
- security impact is unclear
- acceptance criteria cannot be satisfied
- tests are nondeterministic
- production access is requested
- task scope expands materially
- external system behavior is ambiguous
- the bot would need to weaken a safety control

## 14. Workforce Metrics

Track:

- task cycle time
- first-pass success rate
- rework rate
- CI failure rate
- escaped defect rate
- security finding rate
- mean time to repair
- agent tool-call count
- model token usage
- model cost
- blocked-task rate
- review rejection rate
- release rollback rate

Agent productivity must never be measured only by number of commits.

## 15. Human Control Plane

Human approvals are required for:

- production deployment
- security-policy changes
- authentication/authorization changes
- destructive database migrations
- changes to safety-critical workflows
- changes to external payment or communication authority
- changes to model/tool permissions
- release of major versions

## 16. Auditability

Every bot action records:

- bot identity/version
- task ID
- Jira issue
- Git commit/PR
- tool used
- timestamp
- authorization context
- result
- error
- retry number
- model/provider
- token/cost metadata where available

## 17. Workforce Security

- short-lived credentials
- secret manager
- no credentials in prompts
- tool allowlists
- network egress restrictions
- repository path restrictions
- signed artifacts where practical
- dependency and secret scanning
- SBOM generation
- immutable audit logs

## 18. Definition of Autonomous Completion

A bot may mark implementation complete only when:

1. acceptance criteria are satisfied
2. required tests pass
3. security checks pass or have accepted findings
4. documentation is updated
5. Jira status is synchronized
6. PR is ready for independent review

