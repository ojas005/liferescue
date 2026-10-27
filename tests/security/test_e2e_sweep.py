"""KAN-45 step 6 tests: end-to-end sink sweep (T-23) and negative control (T-24).

A simulated task exercises logs, errors, prompts, audit, persistence and PR/Jira text helpers with seeded
canaries (generated at runtime). Every output sink is then searched literally for each canary and its
encodings, and, when the pinned scanner is available, scanned with scripts/security/scan-paths.sh.
T-24 repeats the simulation with redaction switched OFF (patched inside the test only) and requires the
sweep to FIND leaks, proving the sweep and the T-16 checks can fail.
"""

import base64
import logging
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import quote

from packages.secrets.codes import RevokeReason
from packages.secrets.errors import SecretLeak
from packages.secrets.guards import RedactingAuditSink, RedactingLogFilter, SinkGuards
from packages.secrets.logging_rules import StreamAuditSink
from packages.secrets.redaction import Redactor
from packages.secrets.testing import random_chars
from tests.security.fixtures_broker import DB_REF, MODEL_REF, SEARCH_REF, Rig
from tests.security.scenarios import emit_through_sinks, leaks_in

ROOT = Path(__file__).resolve().parents[2]
SCAN_SCRIPT = ROOT / "scripts" / "security" / "scan-paths.sh"


def simulate_task(workdir: Path) -> dict:
    """Run a gateway-style task that touches every sink. Returns {sink_file: Path} and the canaries."""
    rig = Rig(tasks=(("T-1", "R-1", "LR-06"), ("T-2", "R-2", "LR-04")))
    sinks = {
        name: workdir / name
        for name in (
            "app.log",
            "audit.jsonl",
            "prompts.txt",
            "outgoing.txt",
            "errors.txt",
            "db.sqlite",
            "db_dump.sql",
        )
    }

    audit_file = open(sinks["audit.jsonl"], "w", encoding="utf-8")  # noqa: SIM115 - handle lifetime spans the test

    rig.broker.audit_sink = RedactingAuditSink(
        StreamAuditSink(audit_file), rig.broker.redactor
    )

    logger = logging.getLogger("kan45.e2e." + random_chars(8))
    logger.propagate = False
    logger.setLevel(logging.DEBUG)
    fh = logging.FileHandler(sinks["app.log"], encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    fh.addFilter(RedactingLogFilter(rig.broker.redactor))
    logger.addHandler(fh)

    guards = SinkGuards(rig.broker)
    h_model = rig.request(MODEL_REF)
    h_search = rig.request(SEARCH_REF)
    h_db = rig.request(DB_REF, task="T-2", run="R-2", agent="LR-04")
    canaries = [rig.canaries[MODEL_REF], rig.canaries[SEARCH_REF], rig.canaries[DB_REF]]
    pattern_key = "xai-" + random_chars(48)  # a key-shaped string that was never leased

    db = sqlite3.connect(sinks["db.sqlite"])
    db.execute("create table checkpoints (run_id text, state text)")
    prompts = open(sinks["prompts.txt"], "w", encoding="utf-8")  # noqa: SIM115 - handle lifetime spans the test
    outgoing = open(sinks["outgoing.txt"], "w", encoding="utf-8")  # noqa: SIM115 - handle lifetime spans the test
    errors = open(sinks["errors.txt"], "w", encoding="utf-8")  # noqa: SIM115 - handle lifetime spans the test

    for handle, gateway in (
        (h_model, "model-gateway"),
        (h_search, "tool-gateway"),
        (h_db, "tool-gateway"),
    ):
        # --- gateway call: the value exists only inside this block; the provider echoes it in errors ---
        with rig.use(handle, gateway=gateway) as secret:  # noqa: SIM117 - nested contexts kept for readability of the security test
            with secret.reveal() as raw:
                provider_body = f"HTTP 401 invalid credential {raw}; sent as {base64.b64encode(raw.encode()).decode()} / {quote(raw, safe='')}"
                logger.info("provider call using %s", raw)
                logger.error("provider said: %s", provider_body)
                try:
                    raise RuntimeError(provider_body)
                except RuntimeError:
                    logger.exception("gateway failed")

                def _failing_call(b: str = provider_body) -> None:
                    raise RuntimeError(b)

                result = guards.run_provider_call(_failing_call)
                errors.write(repr(result) + "\n")
                errors.write(
                    rig.broker.redactor.format_traceback(RuntimeError(provider_body))
                    + "\n"
                )
        # --- prompt builder: raw tool output must be refused, the agent-visible (redacted) text accepted ---
        tool_output = f"upstream error: {provider_body} extra {pattern_key}"
        for candidate in (tool_output, result["error"]):
            try:
                guards.prompt(candidate)
                prompts.write("PROMPT: " + candidate + "\n")
            except SecretLeak:
                prompts.write("PROMPT REFUSED\n")
        # --- persistence ---
        for state in (f"tool said {provider_body}", "phase: planning"):
            try:
                guards.persist(
                    {"run_id": handle.run_id, "state": state},
                    lambda rec: db.execute(
                        "insert into checkpoints values (?, ?)",
                        (rec["run_id"], rec["state"]),
                    ),
                )
            except SecretLeak:
                pass
        # --- PR / Jira text helpers ---
        for text in (
            f"Debug output: {provider_body}",
            "Looks good, merging after review",
        ):
            try:
                outgoing.write(guards.outgoing(text) + "\n")
            except SecretLeak:
                outgoing.write("OUTGOING REFUSED\n")
    logger.warning("key-shaped string seen: %s", pattern_key)
    rig.broker.revoke_task("T-1", reason_code=RevokeReason.TASK_END)

    db.commit()
    sinks["db_dump.sql"].write_text("\n".join(db.iterdump()), encoding="utf-8")
    db.close()
    for f in (audit_file, prompts, outgoing, errors):
        f.close()
    fh.close()
    return {
        "sinks": sinks,
        "canaries": canaries,
        "pattern_key": pattern_key,
        "rig": rig,
    }


def sweep(sim: dict) -> dict:
    """Literal search of every sink for each canary and its encodings. Returns {file: [(canary_index, form)]}."""
    hits = {}
    for name, path in sim["sinks"].items():
        data = path.read_bytes()
        text = data.decode("utf-8", "replace")
        found: list[tuple[int | str, str]] = []
        for i, canary in enumerate(sim["canaries"]):
            found += [(i, f) for f in leaks_in(text, canary)]
        if sim["pattern_key"] in text:
            found.append(("pattern", "raw"))
        if found:
            hits[name] = found
    return hits


class EndToEndSweep(unittest.TestCase):
    def test_T23_no_sink_contains_a_canary_or_its_encodings(self):
        with tempfile.TemporaryDirectory() as d:
            sim = simulate_task(Path(d))
            for name, path in sim["sinks"].items():
                self.assertGreater(
                    path.stat().st_size,
                    0,
                    f"sink {name} is empty: the sweep would prove nothing",
                )
            self.assertEqual(sweep(sim), {})
            logs = sim["sinks"]["app.log"].read_text()
            self.assertIn("[REDACTED:secret]", logs)
            self.assertIn("[REDACTED:xai_key]", logs)
            self.assertIn("PROMPT REFUSED", sim["sinks"]["prompts.txt"].read_text())
            self.assertIn("OUTGOING REFUSED", sim["sinks"]["outgoing.txt"].read_text())
            self.assertIn("planning", sim["sinks"]["db_dump.sql"].read_text())
            # every redaction/block was counted by kind and sink, without content
            snapshot = sim["rig"].broker.metrics.snapshot()
            self.assertTrue(any(k.startswith("redactions{") for k in snapshot))
            self.assertNotIn(sim["canaries"][0], repr(snapshot))
            # audit events for the whole run contain no canary and include the blocks
            audit = sim["sinks"]["audit.jsonl"].read_text()
            self.assertIn("redaction_blocked", audit)

    def test_T23_scanner_over_every_sink_when_available(self):
        if not SCAN_SCRIPT.is_file():
            self.skipTest(
                "SKIPPED: scripts/security/scan-paths.sh is not in the repository yet (proposed LR 08 control)"
            )
        if shutil.which("gitleaks") is None:
            self.skipTest(
                "SKIPPED: gitleaks (pinned 8.30.1) is not installed on this machine"
            )
        with (
            tempfile.TemporaryDirectory() as d
        ):  # pragma: no cover - depends on tooling
            simulate_task(Path(d))
            proc = subprocess.run(
                ["bash", str(SCAN_SCRIPT), d],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(
                proc.returncode,
                0,
                "scanner found a possible secret in an output sink (details redacted by the scanner)",
            )

    def test_sweep_checker_itself_detects_planted_leaks(self):
        with tempfile.TemporaryDirectory() as d:
            sim = simulate_task(Path(d))
            canary = sim["canaries"][1]
            with open(sim["sinks"]["errors.txt"], "a", encoding="utf-8") as fh:
                fh.write(
                    "planted "
                    + base64.urlsafe_b64encode(canary.encode()).decode().rstrip("=")
                    + "\n"
                )
            with open(sim["sinks"]["app.log"], "a", encoding="utf-8") as fh:
                fh.write("planted " + canary + "\n")
            hits = sweep(sim)
            self.assertIn("errors.txt", hits)
            self.assertIn("app.log", hits)


class NegativeControl(unittest.TestCase):
    """T-24: with redaction disabled (patched here, in the test only), the T-16 and T-23 checks must FAIL."""

    @staticmethod
    def disable_redaction():
        patches = [
            mock.patch.object(
                Redactor, "redact_text", lambda self, text, *, sink="unknown": text
            ),
            mock.patch.object(Redactor, "find_leaks", lambda self, text: ()),
            mock.patch.object(Redactor, "find_leaks_in", lambda self, obj, **kw: ()),
            mock.patch.object(
                Redactor,
                "redact_exception",
                lambda self, exc, *, sink="unknown": Redactor.redact_exception_raw_text(
                    exc
                ),
            ),
        ]
        return patches

    def test_T24_sink_sweep_finds_leaks_when_redaction_is_off(self):
        patches = self.disable_redaction()
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        with tempfile.TemporaryDirectory() as d:
            sim = simulate_task(Path(d))
            hits = sweep(sim)
        self.assertTrue(hits, "the sweep must fail when redaction is disabled")
        self.assertGreaterEqual(
            len(hits),
            4,
            f"expected leaks in several sinks, found only in {sorted(hits)}",
        )

    def test_T24_T16_scenarios_find_leaks_when_redaction_is_off(self):
        rig = Rig()
        rig.request()
        canary = rig.canaries[MODEL_REF]
        clean = emit_through_sinks(rig, canary)
        self.assertTrue(
            all(not leaks_in(t, canary) for t in clean.values()),
            "baseline must be clean",
        )
        patches = self.disable_redaction()
        for p in patches:
            p.start()
        try:
            leaky = emit_through_sinks(rig, canary)
        finally:
            for p in patches:
                p.stop()
        leaking = [name for name, text in leaky.items() if leaks_in(text, canary)]
        self.assertGreaterEqual(
            len(leaking),
            15,
            f"only {len(leaking)} scenarios leaked with redaction off: {leaking}",
        )

    def test_T24_guards_stop_blocking_when_redaction_is_off(self):
        rig = Rig()
        rig.request()
        guards = SinkGuards(rig.broker)
        text = f"key {rig.canaries[MODEL_REF]}"
        with self.assertRaises(SecretLeak):
            guards.prompt(text)
        patches = self.disable_redaction()
        for p in patches:
            p.start()
        try:
            guards.prompt(
                text + " (different text)"
            )  # no longer refused: proves the guard depends on the redactor
        finally:
            for p in patches:
                p.stop()


if __name__ == "__main__":
    unittest.main()
