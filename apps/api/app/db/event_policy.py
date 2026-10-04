"""Timeline payload allowlist per event type (SECURITY P1).

Only the fields below are stored. Anything else (raw prompts, raw model output, chain of thought, raw tool responses,
unknown keys) is dropped and the dropped KEY NAMES are recorded under ``_dropped`` so a developer notices.
If the runtime needs another field, add it HERE in a reviewed change (LR 04 + LR 08)."""

from __future__ import annotations

from typing import Any

from contract.models import EventType

ALLOWED_KEYS: dict[EventType, frozenset[str]] = {
    EventType.STATE_CHANGE: frozenset({"from", "to", "reason", "note"}),
    EventType.INTENT: frozenset({"summary", "category", "urgency", "entities", "model", "adapter"}),
    EventType.EVIDENCE: frozenset({"collected", "missing"}),
    EventType.RESEARCH: frozenset({"queries", "skipped", "source_urls", "result_count"}),
    EventType.PLAN: frozenset({"summary", "steps"}),
    EventType.POLICY: frozenset(
        {"step_id", "tool", "outcome", "risk", "rule_id", "reason", "policy_version", "action_digest"}
    ),
    EventType.APPROVAL: frozenset(
        {"approval_id", "step_id", "status", "summary", "expires_at", "decided_by", "action_digest"}
    ),
    EventType.ACTION: frozenset(
        {"step_id", "tool", "status", "mocked", "simulated", "output", "error", "action_digest"}
    ),
    EventType.VERIFICATION: frozenset({"passed", "checks"}),
    EventType.AUDIT: frozenset({"audit_records", "chain_head_before_summary"}),
    EventType.ERROR: frozenset({"reason", "code"}),
}

_MAX_STR = 2000


def _bound(value: Any, depth: int = 0) -> Any:
    if isinstance(value, str):
        return value if len(value) <= _MAX_STR else value[:_MAX_STR] + "...[truncated]"
    if isinstance(value, dict) and depth < 6:
        return {str(k): _bound(v, depth + 1) for k, v in value.items()}
    if isinstance(value, list) and depth < 6:
        return [_bound(v, depth + 1) for v in value[:100]]
    return value if isinstance(value, (int, float, bool)) or value is None else str(value)[:_MAX_STR]


def allowlist_payload(event_type: EventType, payload: dict[str, Any]) -> dict[str, Any]:
    allowed = ALLOWED_KEYS[event_type]
    out = {k: v for k, v in payload.items() if k in allowed}
    dropped = sorted(str(k) for k in payload if k not in allowed)
    # Non-simulated tool output is a raw tool response: keep only its shape, never the content.
    if (
        event_type == EventType.ACTION
        and "output" in out
        and not (payload.get("mocked") or payload.get("simulated"))
    ):
        o = out["output"]
        out["output"] = (
            {"keys": sorted(map(str, o))[:20]} if isinstance(o, dict) else {"type": type(o).__name__}
        )
    bounded: dict[str, Any] = _bound(out)
    if dropped:
        bounded["_dropped"] = dropped[:20]
    return bounded
