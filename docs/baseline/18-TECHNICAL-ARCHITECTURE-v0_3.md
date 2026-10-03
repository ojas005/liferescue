# LifeRescue — Technical Architecture v0.3

## 1. Architecture Decision

The initial implementation uses a modular service architecture with clear boundaries.

Recommended baseline:

- Web: Next.js + TypeScript
- API: Python + FastAPI
- Agent runtime: Python
- Database: PostgreSQL
- Cache/coordination: Redis
- Async messaging: managed event bus
- Object storage: S3-compatible object storage
- AI inference: Nebius AI Cloud / Token Factory using NVIDIA open models such as Nemotron
- Research: Tavily
- Engineering workforce: Grok/xAI tooling
- Work management: Jira + Confluence
- Source control: GitHub or Bitbucket
- Containers: Docker
- Infrastructure: Terraform
- Observability: OpenTelemetry + metrics/logging/tracing backend

This is a baseline and may be revised through ADRs.

## 2. Service Boundaries

### API Gateway/BFF
Responsibilities:
- authentication integration
- request validation
- rate limiting
- correlation IDs
- API versioning

### Incident Service
Responsibilities:
- incident lifecycle
- domain state
- facts
- evidence references
- actions
- approvals

### Agent Orchestrator
Responsibilities:
- state-machine execution
- agent selection
- step budgets
- retries
- timeouts
- checkpoints
- escalation

### Policy Engine
Responsibilities:
- authorization
- action risk classification
- approval requirements
- tool allowlists
- data access rules

The LLM must not be the final policy authority.

### Tool Gateway
All external actions pass through one governed boundary.

Responsibilities:
- authentication
- authorization
- schema validation
- idempotency
- rate limits
- audit
- timeout
- response normalization

### Evidence Service
Responsibilities:
- source registration
- provenance
- timestamps
- confidence
- evidence classification
- attachment metadata

### Notification Service
Responsibilities:
- user notifications
- delivery tracking
- retries
- preference enforcement

### Verification Service
Responsibilities:
- verify claimed external outcomes
- reconcile action state
- detect partial success

## 3. AI Model Gateway

Never couple domain services directly to one model provider.

```text
Agent
  -> Model Gateway
      -> Provider Adapter
          -> Nebius/NVIDIA Model
```

Model gateway provides:
- model selection
- prompt/version metadata
- structured output validation
- timeout
- token/cost metadata
- fallback policy
- safety policy
- telemetry

Customer-facing inference should use the hackathon-required Nebius/NVIDIA path.

## 4. Agent Runtime

```text
Incident
  -> Context Builder
  -> Planner
  -> Policy
  -> Tool Selection
  -> Tool Gateway
  -> Evidence
  -> Verifier
  -> Next State
```

Agents do not directly access:
- database credentials
- production network credentials
- raw secret stores
- unrestricted internet
- unrestricted shell

## 5. Data Model

Core tables:

### users
- id UUID PK
- external_subject
- status
- created_at
- updated_at

### incidents
- id UUID PK
- user_id FK
- type
- state
- severity
- location_reference
- created_at
- updated_at
- resolved_at

Indexes:
- user_id + created_at
- state + updated_at
- severity + state

### incident_facts
- id UUID PK
- incident_id FK
- fact_type
- value_json
- source
- confidence
- observed_at
- created_at

### evidence
- id UUID PK
- incident_id FK
- type
- source
- content_reference
- provenance_json
- confidence
- captured_at

### actions
- id UUID PK
- incident_id FK
- action_type
- status
- risk_level
- idempotency_key UNIQUE
- request_json
- result_json
- created_at
- completed_at

### approvals
- id UUID PK
- action_id FK
- requested_from
- status
- decision
- decided_at
- reason

### agent_runs
- id UUID PK
- incident_id FK
- agent_type
- prompt_version
- model
- status
- step_count
- token_metadata
- started_at
- completed_at

### audit_events
- id UUID PK
- actor_type
- actor_id
- event_type
- resource_type
- resource_id
- metadata_json
- occurred_at

## 6. Data Rules

- UUID identifiers
- UTC timestamps
- database migrations only
- foreign keys for integrity
- unique constraints for idempotency
- JSON only where schema flexibility is justified
- sensitive fields classified explicitly
- retention policy documented per data class
- no secrets in database

## 7. API Standards

Base path:

`/v1`

Required headers:
- Authorization
- X-Request-ID
- Idempotency-Key for mutating operations where duplication is unsafe

Error model:

```json
{
  "error": {
    "code": "ACTION_NOT_AUTHORIZED",
    "message": "The requested action requires approval.",
    "requestId": "req_123",
    "details": {}
  }
}
```

Never expose internal stack traces.

## 8. Incident State Machine

```text
CREATED
 -> UNDERSTANDING
 -> SAFETY_CHECK
 -> CONTEXT_COLLECTION
 -> RESEARCH
 -> PLAN
 -> POLICY_CHECK
 -> WAITING_FOR_APPROVAL
 -> EXECUTING
 -> VERIFYING
 -> COMPLETED
```

Alternative failure states:

- TOOL_FAILED
- EVIDENCE_INSUFFICIENT
- AUTHORIZATION_FAILED
- TIMEOUT
- POLICY_BLOCKED
- USER_CANCELLED

All transitions must be explicit and auditable.

## 9. Tool Contract

Every tool defines:

```json
{
  "name": "find_assistance",
  "version": "1.0",
  "riskLevel": "medium",
  "inputSchema": {},
  "outputSchema": {},
  "requiresApproval": false,
  "idempotent": true,
  "timeoutSeconds": 10
}
```

Tool outputs are untrusted data and must be schema validated.

## 10. Approval Engine

Actions classified as:
- low risk: automatic
- medium risk: conditional
- high risk: explicit user approval
- critical: human approval plus policy gate

Examples of high/critical:
- payment
- legally consequential communication
- sharing sensitive data
- irreversible action
- emergency escalation

Approval is bound to:
- exact action
- exact parameters
- expiration
- user identity
- policy version

Approval cannot be reused for a materially different action.

## 11. Reliability

Required:
- timeouts
- bounded retries
- exponential backoff
- idempotency
- circuit breakers
- dead-letter handling
- checkpointed agent state
- graceful degradation
- explicit partial failure

No infinite agent loops.

## 12. Security Architecture

Controls:
- OAuth/OIDC
- RBAC/ABAC
- secret manager
- encryption in transit and at rest
- network segmentation
- dependency scanning
- secret scanning
- container scanning
- SBOM
- audit logs
- rate limits
- WAF/API protection
- prompt-injection defenses
- tool allowlists

## 13. Observability

Every request carries:
- request ID
- trace ID
- incident ID
- agent run ID
- Jira issue ID where applicable

Metrics:
- API latency
- error rate
- queue depth
- agent duration
- tool latency
- model latency
- token usage
- cost
- state transition failures
- verification failures

Logs must not contain secrets or unnecessary sensitive data.

## 14. Deployment

Environments:

```text
local
  -> development
  -> staging
  -> production
```

Promotion requires automated verification.

Production deployment:
- release candidate
- security gates
- smoke tests
- migration checks
- approval
- deployment
- post-deployment verification
- rollback readiness

## 15. Disaster Recovery

Define and test:
- RPO
- RTO
- database backups
- backup restoration
- object storage recovery
- queue recovery
- regional failure behavior
- degraded AI behavior

Targets must be selected before production launch rather than assumed.

## 16. Architecture Quality Gates

A service cannot be production-ready until it has:

- API contract
- data model
- authorization
- validation
- tests
- observability
- failure handling
- security review
- deployment definition
- rollback strategy
- documentation

