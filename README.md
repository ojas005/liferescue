# LifeRescue — AI Emergency Coordination & Readiness Platform

> **Hackathon Edition (NVIDIA / Nebius AI Cloud)**  
> Production-quality, governed AI emergency response platform combining acute triage, coordinated safety response, and proactive personal preparedness.

---

## 1. Executive Summary

**LifeRescue** is a security-first, auditable emergency coordination system designed to assist people during life-threatening crises and help them prepare before emergencies strike.

Instead of generic chatbot conversations, LifeRescue operates through **governed state machines**, **deterministic safety policies**, and **defense-in-depth secret redaction**.

### Three Core Capabilities Inside One Unified Application

```
                     ┌─────────────────────────────────────────┐
                     │            LifeRescue UI                │
                     │  (Dashboard • Triage • Timeline • Readiness)
                     └────────────────────┬────────────────────┘
                                          │
                                          ▼
                     ┌─────────────────────────────────────────┐
                     │            REST API Gateway             │
                     │   (/incidents, /profile, /contacts)     │
                     └────────────────────┬────────────────────┘
                                          │
    ┌─────────────────────────────────────┼─────────────────────────────────────┐
    │                                     │                                     │
    ▼                                     ▼                                     ▼
┌──────────────────────────┐  ┌──────────────────────────┐  ┌──────────────────────────┐
│       Capability A       │  │       Capability B       │  │       Capability C       │
│  Emergency Understanding │  │     Emergency Action     │  │    Personal Emergency    │
│        & Triage          │  │  Response Coordination   │  │   Readiness & Prevention │
└────────────┬─────────────┘  └────────────┬─────────────┘  └────────────┬─────────────┘
             │                             │                             │
             │ AI Triage                   │ Vetted Action Plan          │ Preparedness Score
             ▼                             ▼                             ▼
┌──────────────────────────┐  ┌──────────────────────────┐  ┌──────────────────────────┐
│   Safety Policy Engine   │──▶│   Response Orchestrator  │  │ Profile & Contacts Repo  │
│(Deterministic Guardrails)│  │ (Simulation / Dispatch)  │  │   (Defensive Redaction)  │
└──────────────────────────┘  └────────────┬─────────────┘  └──────────────────────────┘
                                           │
                        ┌──────────────────┴──────────────────┐
                        ▼                                     ▼
           ┌─────────────────────────┐           ┌─────────────────────────┐
           │      Timeline Audit     │           │   Notification Provider │
           │   (Full Event History)  │           │   (Simulated / Dispatched)
           └─────────────────────────┘           └─────────────────────────┘
```

- **Capability A — Emergency Understanding & Triage:**  
  Accepts unstructured natural language, structured reports, voice transcripts, or sensor alerts. Extracts key facts, classifies urgency (Low, Medium, High, Critical), highlights missing life-critical details (location, consciousness), and prioritizes emergency escalation.
- **Capability B — Emergency Action & Response Coordination:**  
  Translates triage analysis into actionable response steps (dispatching emergency responders, alerting primary contacts, assembling responder medical dossiers, and displaying first-aid instructions). External notifications run in a governed simulation sandbox during demo mode.
- **Capability C — Personal Emergency Readiness & Prevention:**  
  Proactively audits medical profiles, allergies, medications, and primary contacts. Calculates an instant preparedness score (0–100%) and identifies specific vulnerabilities before an emergency occurs.

---

## 2. Key Architecture Principles

1. **Deterministic Safety Policy Boundary:**  
   The LLM is never the final policy authority. Proposed actions pass through `SafetyPolicyEngine` which enforces action allowlists, blocks unsafe/prohibited instructions (such as prescriptive drug dosing, shell execution, or financial transfers), and forces emergency escalation for life-threatening conditions (e.g., chest pain, breathing compromise, heavy bleeding).
2. **Provider-Agnostic AI Gateway:**  
   Runs locally without any external credentials using `MockAIProvider`. Connects to NVIDIA NIM or Nebius AI Cloud via `NVIDIAAIProvider` adapter boundary when configured via environment variables.
3. **Defense-in-Depth Secret Redaction (KAN-45):**  
   Every log line, exception, database write, API response, and audit trail record is guarded by the KAN-45 `Redactor`. Canaries and API keys are scrubbed before reaching any persistence layer or client.
4. **Governed Auditability:**  
   Every state change, triage evaluation, policy ruling, and action execution generates a tamper-evident structured `AuditEvent`.

---

## 3. Quickstart (Zero External Credentials Required)

LifeRescue is designed to run locally right out of the box with zero external API keys.

### 1. Requirements
- Python 3.11+
- Standard libraries + FastAPI / Uvicorn (already in dependencies)

### 2. Launch the Application

```bash
python apps/api/run.py
```

### 3. Open the Experience
- **Interactive Web App:** [http://127.0.0.1:8000](http://127.0.0.1:8000)
- **Interactive OpenAPI Documentation:** [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- **Health Endpoint:** [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health)

---

## 4. One-Click Hackathon Scenarios

The web interface includes interactive one-click demonstration scenarios:

1. **Scenario 1 — Acute Medical Emergency:**  
   Patient reports severe crushing chest pain radiating to left arm and shortness of breath. LifeRescue detects critical cardiovascular compromise, mandates 911 dispatch, alerts the primary spouse contact, compiles a paramedic medical dossier, and renders calm first-aid steps.
2. **Scenario 2 — Highway Traffic Collision:**  
   Multi-vehicle collision on interstate with passenger injury. LifeRescue extracts roadway hazards, flags missing vehicle counts, and coordinates emergency dispatch.
3. **Scenario 3 — Wildfire / Hazmat Evacuation:**  
   Approaching ridge fire with smoke hazard. Triggers immediate evacuation directives and outdoor assembly coordination.

---

## 5. REST API Specification

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/incidents` | Create a new emergency intake |
| `GET` | `/incidents` | List recent incidents |
| `GET` | `/incidents/{id}` | Retrieve incident details |
| `POST` | `/incidents/{id}/analyze` | Trigger AI triage and risk classification |
| `GET` | `/incidents/{id}/analysis` | Retrieve structured AI analysis facts |
| `POST` | `/incidents/{id}/respond` | Generate and execute/simulate response plan |
| `GET` | `/incidents/{id}/timeline` | Retrieve chronological timeline events |
| `GET` | `/emergency-profile` | Get emergency medical profile |
| `PUT` | `/emergency-profile` | Update medical history, allergies, directives |
| `GET` | `/contacts` | List designated emergency contacts |
| `GET` | `/contacts/{id}` | Retrieve single emergency contact |
| `POST` | `/contacts` | Add a new emergency contact |
| `PUT` | `/contacts/{id}` | Update contact details or primary flag |
| `DELETE` | `/contacts/{id}` | Delete an emergency contact |
| `GET` | `/readiness` | Compute preparedness score and gaps |
| `GET` | `/demo/scenarios` | List available demo scenarios |
| `POST` | `/demo/scenarios/{id}/run` | Execute complete end-to-end scenario |
| `GET` | `/audit/events` | Inspect immutable security audit records |
| `GET` | `/health` | Service status and runtime flags |

---

## 6. Testing & Quality Assurance

LifeRescue includes a comprehensive, multi-layer automated test suite:

```bash
# Run Unit Tests (Domain models, safety engine, storage, AI providers)
python -m unittest discover -s tests/unit

# Run Integration Tests (FastAPI endpoints, middleware, headers, audit)
python -m unittest discover -s tests/integration

# Run End-to-End Workflow Tests (Scenarios 1-3, readiness lifecycle)
python -m unittest discover -s tests/e2e

# Run Security & Secret Redaction Suite (KAN-45)
python -m unittest discover -s tests/security
```

**Total Passing Tests:** 248 passed, 0 failures, 1 skipped (249 total).

---

## 7. Connecting Real NVIDIA / Nebius AI Keys (Optional)

When real inference API keys are available, simply configure `.env` (or set environment variables):

```env
AI_PROVIDER=nebius
NEBIUS_API_KEY=<your Nebius Token Factory key>   # never commit; NVIDIA_API_KEY is an alias
NVIDIA_MODEL=nvidia/nemotron-3-super-120b-a12b
NVIDIA_BASE_URL=https://api.tokenfactory.nebius.com/v1/
```

Only incident triage (analysis) is model-backed; response plans and readiness stay deterministic. Model output is schema-validated and always passes the deterministic `SafetyPolicyEngine` before any (simulated) action. If the provider is unreachable, times out, rejects the key, or returns invalid JSON, LifeRescue falls back to the deterministic triage provider and labels it visibly: `provider_name` becomes `nvidia_ai (mock_fallback: <reason>)`, `/health` reports `ai_mode: "fallback"`, the audit event carries `fallback: true`, and the UI badge says MOCK fallback. Run `python scripts/smoke_nvidia.py` to verify a live call.

---

## 8. License

LifeRescue is released under the MIT License. See [LICENSE](LICENSE) for details.
