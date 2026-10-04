# tests/fixtures

Synthetic, hand-authored test data. **Nothing here is a real recording, real model output or real personal data**; every file has `_meta.synthetic: true`. Secrets are obviously fake (marker `LRQA`) and live in `redaction/` (not `secrets/`, which `.gitignore` excludes).

| Dir | Content |
|---|---|
| `tavily/` (8) | Tavily-style search results per workflow (`.example` domains). Response shape written from memory, not recorded. |
| `mock_model/` (6) | canned `IntentResult` / `PlanProposal` / `AssessmentResult` per workflow plus `variants` with an `_expect` note, and `_negative_outputs.json` (schema-invalid replies). Validated against contract 0.1.0 types. |
| `golden/` (4 files, 19 cases) | scam, prompt-injection, vehicle_breakdown, life_admin cases with expected behaviour. Only `vehicle_breakdown` inputs are validated against a contract input schema (the contract has no scam/life_admin definitions). |
| `redaction/` (1) | `fake_secrets.json`: RS-001..RS-010 for the redaction gap (finding F3). |

`python tests/fixtures/validate_fixtures.py` checks all of it; `tests/conformance/test_fixtures_valid.py` runs it and replays the vehicle fixtures through the fake stack. LR 08's security corpora are referenced elsewhere, not copied here.
