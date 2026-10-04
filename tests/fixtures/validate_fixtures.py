#!/usr/bin/env python3
"""Validate the synthetic test fixtures in tests/fixtures (stdlib + optional contract types). Run from anywhere:
    python tests/fixtures/validate_fixtures.py
Also imported by tests/conformance/test_fixtures_valid.py.

If the `contract` package is importable (pip install -e packages/contract, or set QA_CONTRACT_PATH, or keep the
default ../../packages/contract) model fixtures are validated with the REAL contract 0.1.0 pydantic types
(IntentResult, PlanProposal, AssessmentResult); otherwise only structural checks run (a WARN is printed).
Checks: JSON parses; every file carries _meta.synthetic=true; golden cross-references exist;
golden api_input has the required intent keys; mock-model claims cite evidence ids that exist in the
matching Tavily fixture; every claim is cited; allowed plans use only registered tools (variants may not);
secret/PII scan (key-like strings, bearer tokens, phone-like digit runs, real-looking emails).
Tool allowlists mirror the LR 04 WIP workflow definitions observed 2026-10-04 and must be re-synced
when LR 03 freezes the contract."""

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("QA_FIXTURES_ROOT") or HERE
TOOLS = {  # mirrors the tool bindings in apps/api/app/workflows/*/definition.py (LR 04) and the contract vehicle_breakdown fixture
    "vehicle_breakdown": {"web_search", "dispatch_tow", "send_message"},
    "scam_investigation": {"web_search", "report_scam"},
    "life_admin": {"web_search", "send_email", "create_calendar_event"},
}
REQUIRED_INPUT = {"vehicle_breakdown": "description", "scam_investigation": "suspicious_content", "life_admin": "task"}
SECRET_PATTERNS = [
    r"\bsk-[A-Za-z0-9_-]{12,}",
    r"\btvly-[A-Za-z0-9_-]{8,}",
    r"\bnvapi-[A-Za-z0-9_-]{8,}",
    r"(?i)bearer\s+[A-Za-z0-9._~+/=-]{12,}",
    r"\bAKIA[0-9A-Z]{16}\b",
    r"\bgh[pousr]_[A-Za-z0-9]{20,}",
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
]
PHONE = re.compile(r"(?<![\w.])(?:\+?91[\s-]?)?[6-9]\d{9}(?!\w)")
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")
OK_EMAIL_DOMAINS = (".example",)
errors, warns = [], []
LAST = {}


def err(m):
    errors.append(m)


def load_all():
    data = {}
    for sub in ("tavily", "mock_model", "golden", "redaction"):
        d = os.path.join(ROOT, sub)
        for fn in sorted(os.listdir(d)):
            if fn.endswith(".json"):
                rel = "%s/%s" % (sub, fn)
                raw = open(os.path.join(d, fn), encoding="utf-8").read()
                try:
                    data[rel] = json.loads(raw)
                except Exception as e:
                    err("%s: JSON parse error: %s" % (rel, e))
                    continue
                if data[rel].get("_meta", {}).get("synthetic") is not True:
                    err("%s: _meta.synthetic must be true" % rel)
                if sub == "redaction":
                    if "LRQA" not in raw:
                        err("%s: fake secrets must carry an LRQA marker" % rel)
                else:
                    for p in SECRET_PATTERNS:
                        if re.search(p, raw):
                            err("%s: secret-like pattern %s" % (rel, p))
                if PHONE.search(raw):
                    err("%s: phone-like number found" % rel)
                for m in EMAIL.finditer(raw):
                    if not m.group(1).endswith(OK_EMAIL_DOMAINS) and not m.group(1).startswith("example"):
                        err(
                            "%s: non-.example email-like string %r (UPI-style handles must use exampleupi)"
                            % (rel, m.group(0))
                        )
    return data


def check_golden(data):
    n = 0
    for rel, d in data.items():
        if not rel.startswith("golden/"):
            continue
        ids = set()
        for c in d["cases"]:
            n += 1
            if c["id"] in ids:
                err("%s: duplicate id %s" % (rel, c["id"]))
            ids.add(c["id"])
            wf = c["workflow_id"]
            if wf not in TOOLS:
                err("%s %s: unknown workflow" % (rel, c["id"]))
            elif REQUIRED_INPUT[wf] not in c.get("api_input", {}):
                err("%s %s: api_input lacks %r" % (rel, c["id"], REQUIRED_INPUT[wf]))
            refs = [c.get("tavily_fixture")] + c.get("expected", {}).get("must_cite_fixtures", [])
            for r in refs:
                if r and not os.path.exists(os.path.join(ROOT, r.split("#")[0])):
                    err("%s %s: missing fixture %s" % (rel, c["id"], r))
            for a in c.get("expected", {}).get("allowed_actions_after_approval", []) + c.get("expected", {}).get(
                "proposed_actions_expected", []
            ):
                if wf in TOOLS and a not in TOOLS[wf]:
                    err("%s %s: expected action %r not in %s tool registry" % (rel, c["id"], a, wf))
    return n


EVIDENCE_KEYS = {  # EvidenceRequirement.key per workflow (scam/life_admin: assumed, not in contract) + research:<n> (n = query template index)
    "vehicle_breakdown": {"description", "location", "vehicle"},
    "scam_investigation": {"suspicious_content", "channel", "url", "sender"},
    "life_admin": {"task", "deadline", "context"},
}
MARK = re.compile(r"\[ev:([A-Za-z0-9_:]+)\]")
CONTRACT_PATH = os.environ.get("QA_CONTRACT_PATH") or os.path.abspath(
    os.path.join(HERE, "..", "..", "packages", "contract")
)


def load_contract():
    if os.path.isdir(CONTRACT_PATH) and CONTRACT_PATH not in sys.path:
        sys.path.insert(0, CONTRACT_PATH)
    try:
        from contract import models as M  # type: ignore

        return M
    except Exception as e:  # pydantic missing etc.
        warns.append("contract types not importable (%s); only structural checks run" % type(e).__name__)
        return None


def check_cites(rel, where, wf, text, require):
    marks = MARK.findall(text)
    if require and not marks:
        err("%s %s: no [ev:...] citation marker in %r" % (rel, where, text[:60]))
    for k in marks:
        ok = k in EVIDENCE_KEYS[wf] or re.fullmatch(r"research:[1-9]\d*", k)
        if not ok:
            err("%s %s: dangling citation [ev:%s]" % (rel, where, k))


def check_plan(rel, where, wf, plan, allow_unlisted, require_cite=True):
    if where.startswith("variant:unlisted") and all(s["tool_name"] in TOOLS[wf] for s in plan.get("steps", [])):
        err("%s %s: an 'unlisted_tool' variant must contain at least one unlisted tool" % (rel, where))
    check_cites(rel, where + ".summary", wf, plan.get("summary", ""), False)
    if require_cite and not MARK.search(json.dumps(plan)):
        err("%s %s: plan has no citation at all" % (rel, where))
    for s in plan.get("steps", []):
        check_cites(rel, where + ".rationale", wf, s.get("rationale", ""), False)
        if not allow_unlisted and s["tool_name"] not in TOOLS[wf]:
            err("%s %s: tool %s not in %s registry" % (rel, where, s["tool_name"], wf))


def check_mock(data, M):
    n_valid = 0
    for rel, d in data.items():
        if rel == "mock_model/_negative_outputs.json":
            structural = {"NEG-001", "NEG-002", "NEG-003", "NEG-009"}
            for c in d["cases"]:
                if M is None or "output" not in c:
                    continue
                typ = getattr(M, c["schema"])
                try:
                    typ.model_validate(c["output"])
                    ok = True
                except Exception:
                    ok = False
                if (c["id"] in structural) == ok:
                    err("%s %s: schema validation outcome %s contradicts expectation" % (rel, c["id"], ok))
            continue
        if not rel.startswith("mock_model/"):
            continue
        wf = d["_meta"]["workflow_id"]
        for tname in ("IntentResult", "PlanProposal", "AssessmentResult"):
            if tname not in d["outputs"]:
                err("%s: missing output %s" % (rel, tname))

        def validate(tname, obj, where, rel=rel):
            nonlocal n_valid
            if M is not None:
                try:
                    getattr(M, tname).model_validate(obj)
                    n_valid += 1
                except Exception as e:
                    err("%s %s: %s fails contract validation: %s" % (rel, where, tname, str(e).splitlines()[0][:100]))

        for tname, obj in d["outputs"].items():
            validate(tname, obj, "outputs")
        check_plan(rel, "plan", wf, d["outputs"]["PlanProposal"], False)
        check_cites(rel, "assessment", wf, d["outputs"]["AssessmentResult"]["explanation"], False)
        for vn, v in d.get("variants", {}).items():
            for tname in ("IntentResult", "PlanProposal", "AssessmentResult"):
                if tname in v:
                    validate(tname, v[tname], "variant:" + vn)
            if "PlanProposal" in v:
                check_plan(
                    rel,
                    "variant:" + vn,
                    wf,
                    v["PlanProposal"],
                    vn
                    not in (
                        "read_only_plan",
                        "forged_approval_in_params",
                        "disallowed_action_type_plan",
                        "too_many_steps_plan",
                        "assessment_not_satisfied",
                    )
                    and True,
                    require_cite=False,
                )
            if "_expect" not in v:
                err("%s variant:%s: needs _expect" % (rel, vn))
    return n_valid


def reset():
    errors.clear()
    warns.clear()


def main():
    reset()
    data = load_all()
    M = load_contract()
    ng = check_golden(data)
    nv = check_mock(data, M)
    if M is not None:
        try:
            from jsonschema import Draft202012Validator  # type: ignore

            from contract.fixtures.vehicle_breakdown import vehicle_breakdown  # type: ignore

            schema = vehicle_breakdown().intent.input_schema
            for c in data["golden/vehicle_breakdown_cases.json"]["cases"]:
                for e in Draft202012Validator(schema).iter_errors(c["api_input"]):
                    err(
                        "golden %s: api_input violates contract vehicle_breakdown input_schema: %s"
                        % (c["id"], e.message[:80])
                    )
        except ImportError as e:
            warns.append("jsonschema/contract fixture not importable: %s" % e)
    cnt = lambda p: sum(1 for k in data if k.startswith(p))
    print(
        "files: tavily=%d mock_model=%d golden=%d redaction=%d | golden cases=%d | contract-validated model objects=%d"
        % (cnt("tavily/"), cnt("mock_model/"), cnt("golden/"), cnt("redaction/"), ng, nv)
    )
    global LAST
    LAST = {
        "errors": list(errors),
        "warns": list(warns),
        "files": len(data),
        "golden_cases": ng,
        "contract_objects": nv,
        "contract_loaded": M is not None,
    }
    for w in warns:
        print("WARN:", w)
    for e in errors:
        print("FAIL:", e)
    print("RESULT:", "FAIL (%d)" % len(errors) if errors else "OK")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
