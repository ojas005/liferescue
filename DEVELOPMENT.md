# LifeRescue — Local Development Guide

## 1. Prerequisites

- Python 3.11 or newer
- Virtual environment (recommended)
- Git

---

## 2. Setting Up Local Environment

1. **Clone the repository:**
   ```bash
   git clone https://github.com/ojas005/liferescue.git
   cd liferescue
   ```

2. **Install Python dependencies:**
   ```bash
   pip install -r apps/api/requirements.txt  # or install fastapi uvicorn pydantic pydantic-settings httpx
   ```

3. **Configure Environment:**
   ```bash
   cp .env.example .env
   ```
   No external API keys are required for local development or demo runs. `AI_PROVIDER=mock` is active by default.

---

## 3. Running the Application

Launch the LifeRescue web app and REST API server:

```bash
python apps/api/run.py
```

Output:
```text
=================================================================
  LifeRescue — AI Emergency Coordination & Readiness Platform
  AI Provider : mock (deterministic demo mode)
  Local Web UI: http://127.0.0.1:8000
  API Docs    : http://127.0.0.1:8000/docs
=================================================================
```

Open your browser at `http://127.0.0.1:8000`.

---

## 4. Running the Test Suite

LifeRescue includes 239 automated tests covering unit, integration, end-to-end, and security suites:

```bash
# Unit Tests (Domain models, safety engine, storage, AI providers)
python -m unittest discover -s tests/unit

# Integration Tests (FastAPI endpoints, middleware, headers)
python -m unittest discover -s tests/integration

# End-to-End Workflow Tests (Scenarios 1-3, readiness lifecycle)
python -m unittest discover -s tests/e2e

# Security & Secret Redaction Suite (KAN-45)
python -m unittest discover -s tests/security

# Run all suites in one command
python -m unittest discover -s tests/unit; python -m unittest discover -s tests/integration; python -m unittest discover -s tests/e2e; python -m unittest discover -s tests/security
```

---

## 5. Branch Naming & Contribution Rules

Per `CONTRIBUTING.md` and KAN-20 enforcement:
- Branch format: `<type>/KAN-<number>-<description>`
- Allowed types: `feature`, `bugfix`, `security`, `chore`, `docs`
- Example: `feature/KAN-50-emergency-platform`

Verify branch name compliance locally:
```bash
BRANCH_NAME="feature/KAN-50-my-feature" python scripts/ci_branch_gate.py
```

---

## 6. Secret Safety Checks

Never commit secrets or credentials. LifeRescue enforces KAN-45 secret scanning:
```bash
python -m unittest tests/security/test_repo_scan.py
python -m unittest tests/security/test_pattern_parity.py
```
