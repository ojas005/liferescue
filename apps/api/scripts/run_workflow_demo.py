"""End-to-end demo of the agent runtime on the MockAIProvider (deterministic, no network, no keys).

    python apps/api/scripts/run_workflow_demo.py

Runs the test-only `demo_notify` workflow through every stage (intent -> evidence -> research ->
plan -> policy -> approval -> action -> verification -> audit), pauses for approval, approves it as
a demo user, and prints the timeline. Everything the mock produces is labelled MOCK. If
NEBIUS_API_KEY is set it also performs ONE real structured call; otherwise prints "key not provided".
"""

from __future__ import annotations

import asyncio
import os
import sys

from _bootstrap import setup

setup()
os.environ.setdefault("LIFERESCUE_ENV", "dev")  # mock provider is refused in production

from contract.models import ApprovalStatus  # noqa: E402
from demo_support import build_stack  # noqa: E402

from app.runtime.model_gateway import NebiusProvider  # noqa: E402


async def main() -> int:
    st = build_stack()
    print(f"provider={st.provider.model_id} label={st.provider.label!r}")
    run = await st.engine.start("demo_notify", {"message": "my car broke down on the highway"})
    print(f"after start: state={run.state.value}")
    pending = [
        a for a in await st.approvals.list_for_run(run.run_id) if a.status == ApprovalStatus.PENDING
    ]
    for ap in pending:
        print(f"approval requested: {ap.approval_id} -> approving as demo-user")
        run = await st.engine.decide_approval(run.run_id, ap.approval_id, True, "demo-user")
    print(f"final: state={run.state.value} terminal_reason={run.terminal_reason}")
    print("--- timeline ---")
    for ev in await st.store.list_events(run.run_id):
        prov = ev.payload.get("provider")
        tag = f" [{prov['label']}]" if isinstance(prov, dict) and prov.get("label") else ""
        keys = ",".join(sorted(k for k in ev.payload if k != "provider"))[:70]
        print(f"{ev.seq:>3} {ev.step.value:<13} {ev.type.value:<14} payload[{keys}]{tag}")
    print(f"simulated side effects: {st.notified}")

    live = NebiusProvider()
    if live.is_configured():
        print("NEBIUS_API_KEY present -> running scripts/smoke_nebius.py for one real call")
        import smoke_nebius

        return 0 if await smoke_nebius.main() == 0 else 1
    print("real model call: key not provided (NEBIUS_API_KEY unset) - skipped")
    return 0 if run.state.value == "completed" else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
