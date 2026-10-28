# LifeRescue — Devpost Submission Pack (draft)

> Draft only. Nothing here has been submitted. Items marked **PENDING (human)** need Ojas.
> Deadline: **Fri Oct 30 2026, 10:00 PT = 22:30 IST** (official rules §1).

## Track

**Best Apps and Agents**. The rules describe this track as "any app or agent someone would actually use … Power it with Nemotron models on Nebius through Token Factory", which matches LifeRescue: a user-facing app calling Nemotron 3 Super through Token Factory.

## Project origin

LifeRescue was **created during the hackathon Submission Period** (which opened Aug 26, 2026). It is not a pre-existing project.

## Tagline

Emergency triage and response coordination where **AI proposes and deterministic safety policy decides**.

## Description (Devpost text)

**The problem.** In the first minutes of a cardiac event, a road collision or a wildfire, people panic and lose time. An LLM chatbot can help, but on its own it can under-rate a life threat, be prompt-injected, or invent actions.

**What LifeRescue does.** One workflow, **PREPARE → EMERGENCY → UNDERSTAND → DECIDE SAFELY → RESPOND → LEARN**:
- **Prepare:** an emergency profile, contacts and a readiness score with gaps.
- **Understand:** NVIDIA Nemotron (`nvidia/nemotron-3-super-120b-a12b`) on Nebius Token Factory turns free text into a structured, schema-validated analysis (category, severity, missing info).
- **Decide safely:** the deterministic `SafetyPolicyEngine` enforces a life-threat urgency floor (the model can only raise urgency), an action allowlist, prohibited-action patterns and prompt-injection flagging. Steps come from a vetted library, and "call 112/911" is always shown.
- **Respond:** the `ResponseOrchestrator` runs the vetted plan as **clearly labelled simulations** ([SIMULATED DISPATCH], [SIMULATED SMS]). Nothing contacts real services.
- **Learn:** every analysis, decision and action goes to an append-only audit log, with secret redaction on logs, DB and API responses.

**How we use NVIDIA and Nebius.** Each incident analysis is a runtime call to the Nebius Token Factory OpenAI-compatible API (`https://api.tokenfactory.nebius.com/v1/`) serving Nemotron 3 Super. If the call fails or returns invalid JSON, the app falls back to deterministic triage and labels it visibly (badge "MOCK fallback", `/health` `ai_mode: fallback`).
Verified on 2026-10-27 (IST):
- The smoke test returned LIVE OK in 5187 ms with a schema-valid reply. Nemotron said `high`, and the policy raised it to `critical`.
- All three scenarios ran live through the HTTP API, with `/health` reporting `ai_mode: live`.

**Built with:** Python, FastAPI, Pydantic, SQLite, vanilla JS, NVIDIA Nemotron 3 Super, Nebius Token Factory.

**Try it:** https://liferescue-z4jc.onrender.com (demo token in the testing instructions) · Code: https://github.com/ojas005/liferescue

**Quality:**
- 323 automated tests: 322 pass, and 1 is skipped only when the gitleaks binary is absent.
- ruff, mypy, gitleaks over the full history, pip-audit and a CycloneDX SBOM all run in CI.

**Limitations (honest):** this is a prototype and not a medical device, and all actions are simulated. Nemotron occasionally returns invalid JSON; the fallback is labelled. See README §7c.

## Screenshots (`docs/submission/screenshots/`)

| File | Shows |
|---|---|
| `01-command-center.png` | Command Center dashboard |
| `02-live-triage-cardiac.png` | Scenario 1: cardiac, CRITICAL, simulated actions |
| `03-live-triage-highway.png` | Scenario 2: highway collision |
| `04-live-triage-wildfire.png` | Scenario 3: wildfire |
| `timeline.png` | Incident timeline |
| `readiness.png` | Personal readiness |
| `governance.png` | AI governance / safety policy |
| `audit.png` | Audit trail |

These were captured headless in **mock mode** (badge reads MOCK). Re-capture in live mode for the Devpost gallery if you want the LIVE badge visible: PENDING (human, optional).

## Required items checklist (from official rules §4)

| Requirement | Status |
|---|---|
| Working app using Nebius Token Factory at runtime and an NVIDIA open model | ✅ Verified live 2026-10-27 (see README §7) |
| Text description of features | ✅ Draft above |
| Public code repository (GitHub) | ✅ Public since 2026-10-27 (IST): https://github.com/ojas005/liferescue (published at commit `2146883`) |
| Open source license file, visible in the repo's About section | ✅ MIT `LICENSE`; GitHub API reports license `MIT` for the public repo |
| README with setup instructions and NVIDIA/Nebius usage | ✅ README.md |
| URL to working demo / hosted app / test build | ✅ https://liferescue-z4jc.onrender.com (token-gated; give judges the token privately in the Devpost testing instructions). **PENDING (human):** paste the token into the testing instructions |
| Demo video < 3 min, public on YouTube | Recording prepared from the live deployment (not in repo). **PENDING (human):** review it, upload it to YouTube as public, and paste the link |
| Track selection | Best Apps and Agents (matches the rules' description, quoted above). **PENDING (human):** select it on Devpost |
| Feedback on Token Factory / NVIDIA tools | **PENDING (human)**: draft notes below |
| Explanation of updates during the Submission Period (if the project pre-existed) | ✅ Not applicable: LifeRescue was **created during the hackathon Submission Period**; it is not a pre-existing project |
| Free access for judges until judging ends (Dec 15 2026) | Render free tier with demo token. **PENDING (human):** keep the service and the Nebius key active until Dec 15 2026 |

## Feedback draft (for Ojas to edit; facts from our usage only)

- The OpenAI-compatible endpoint made integration simple: one base URL and a model id.
- Nemotron 3 Super sometimes returned replies that weren't valid JSON for a strict schema prompt. We had to build a labelled fallback, so native JSON-schema / structured-output guarantees would help.
- Single-call latency in our smoke test was about 5 s, which is acceptable for triage but noticeable in a live demo UI.
