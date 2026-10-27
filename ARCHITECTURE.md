# LifeRescue — Architecture Documentation

This document describes the technical architecture, security boundaries, and data flow of the **LifeRescue** emergency assistance platform.

---

## 1. High-Level Architecture Diagram

```mermaid
graph TD
    Client[Web UI / Mobile / Sensor Feeds] -->|HTTP / JSON| APIGateway[FastAPI API Layer]
    
    subgraph CorePlatform [LifeRescue Governed Core]
        APIGateway --> IncidentService[Incident Orchestration]
        APIGateway --> ReadinessService[Readiness & Profile Service]
        
        IncidentService --> AIOrchestrator[AI Provider Gateway]
        
        AIOrchestrator -->|Abstract Call| MockAI[Mock AI Provider]
        AIOrchestrator -->|Abstract Call| NVIDIAAI[NVIDIA NIM / Nebius AI Cloud]
        
        AIOrchestrator -->|Untrusted Triage Output| SafetyEngine[Deterministic Safety Policy Engine]
        
        SafetyEngine -->|Vetted Action Plan| ResponseExecutor[Response Executor]
        
        ResponseExecutor --> NotificationProvider[Notification Provider (Simulated / Live)]
    end
    
    subgraph SecurityLayer [Security & Privacy Boundaries]
        SecretBroker[KAN-45 Secret Broker] -->|Lease Management| SecurityGuards[SinkGuards & Redactor]
        SecurityGuards -->|Scrubbed Write| SQLiteDB[(SQLite Repository Storage)]
        SecurityGuards -->|Sanitized Log| AuditLog[(Structured Audit Trail)]
    end

    IncidentService --> SecurityGuards
    ReadinessService --> SecurityGuards
```

---

## 2. Core Subsystems

### 2.1 Capability A: Emergency Understanding & Triage
- **Input Normalization:** Accepts raw user text, structured reports, voice transcript feeds, or sensor alarms.
- **Triage Extraction:** Extracts symptoms, patient risk, scene hazards, conscious status, and missing critical information.
- **Urgency Scoring:** Assigns an urgency class (`low`, `medium`, `high`, `critical`) and severity score (1–10).

### 2.2 Capability B: Emergency Action & Response Coordination
- **Action Plan Generation:** Builds structured actions (`call_emergency_services`, `notify_contact`, `prepare_summary`, `display_instructions`).
- **Deterministic Policy Review:**
  - Mandatory 911/112 escalation if life-threatening patterns are detected (chest pain, respiratory distress, heavy bleeding, stroke, anaphylaxis).
  - Strict Action Allowlist: Discards unvetted or arbitrary action types proposed by LLMs.
  - Prohibited Action Filtering: Drops any action attempting prescriptive medical dosage, financial transfers, or shell execution.
- **Simulation Mode:** During hackathon demos, all external calls (SMS, phone, dispatch) execute in safe simulation mode with clear UI labeling.

### 2.3 Capability C: Personal Emergency Readiness & Prevention
- **Profile Management:** Blood type, known allergies, chronic conditions, current medications, home access directives.
- **Contact Management:** Emergency contacts with primary escalation flags.
- **Readiness Engine:** Computes preparedness score (0–100%) and generates actionable gap remediation items.

---

## 3. Security & Privacy Architecture

### 3.1 Secret Broker & Lease Management (KAN-45)
- All credentials (e.g., model keys, notification tokens) must be leased through `SecretBroker` with explicit purpose codes and TTLs.
- Over-limit TTL requests are strictly **rejected**, never silently trimmed.
- Leases are monotonic-clock tracked and cannot be shared across disparate agent contexts.

### 3.2 Defense-in-Depth Redaction
- The KAN-45 `Redactor` runs on:
  - Application logging (`RedactingLogFilter`)
  - Database persistence (`SQLiteDatabase._sanitize`)
  - Audit logging (`AuditEvent` storage)
  - API responses and exceptions
- Verified by canary regression tests to prevent any secret leak into SQLite, JSON, logs, or outgoing text.

### 3.3 Prompt Injection Defense
- User input is treated strictly as **untrusted data**, never executable instructions.
- System prompt and safety policies reside in immutable code outside the LLM context.
- System instructions cannot be overridden by user inputs (e.g. `ignore previous instructions` triggers defensive safety mode).

---

## 4. Storage & Persistence Layout

LifeRescue uses SQLite behind clean domain repository abstractions:

| Entity | Primary Key | Description |
|---|---|---|
| `users` | `user_id` | Core user identity |
| `emergency_profiles` | `user_id` | Medical history, allergies, instructions |
| `emergency_contacts` | `contact_id` | Designated contacts with primary flags |
| `incidents` | `incident_id` | Emergency incident records |
| `incident_analyses` | `analysis_id` | Recorded AI triage facts |
| `response_plans` | `plan_id` | Vetted response action items |
| `incident_events` | `event_id` | Timeline event sequence |
| `audit_events` | `event_id` | Immutable security audit trail |
