"""KAN-45 step 4 tests: audit event shape and completeness (T-30), logging/telemetry allow-lists (T-18)."""

import io
import json
import logging
import unittest
from datetime import datetime, timedelta, timezone

from fixtures_broker import MODEL_REF, SEARCH_REF, Rig
from packages.secrets.audit import AUDIT_FIELDS, AuditEventType as E, make_event
from packages.secrets.codes import RevokeReason
from packages.secrets.errors import Denied
from packages.secrets.logging_rules import (
    CREDENTIAL_LOGGER_NAME,
    EVENT_ALLOW_LIST,
    FIELD_SHAPES,
    LoggingAuditSink,
    StreamAuditSink,
    allowed_fields,
    install_credential_log_filter,
    log_credential_event,
)
from packages.secrets.telemetry import (
    SafeSpanExporter,
    exception_fields,
    sanitize_span_attributes,
)
from packages.secrets.testing import make_canary
from packages.secrets.tasks import TaskState


def types(rig):
    return [e.event_type for e in rig.sink.events]


class AuditShape(unittest.TestCase):
    def test_event_dict_has_exactly_the_contract_fields_and_types(self):
        rig = Rig()
        h = rig.request()
        rig.use(h)
        self.assertGreaterEqual(len(rig.sink.events), 3)
        ids = set()
        for ev in rig.sink.events:
            d = ev.to_dict()
            self.assertEqual(tuple(d), AUDIT_FIELDS)
            self.assertRegex(d["event_id"], r"^[0-9a-f]{16}$")
            ts = datetime.fromisoformat(d["timestamp"])
            self.assertEqual(ts.utcoffset(), timedelta(0))
            self.assertIsInstance(d["alert"], bool)
            self.assertTrue(d["correlation_id"])
            self.assertEqual(
                (d["task_id"], d["run_id"], d["agent_id"]), ("T-1", "R-1", "LR-06")
            )
            self.assertEqual(d["ref"], MODEL_REF.to_string())
            ids.add(d["event_id"])
            for k, v in d.items():
                self.assertTrue(v is None or isinstance(v, (str, bool)), k)
        self.assertEqual(len(ids), len(rig.sink.events), "event ids are unique")

    def test_correlation_id_propagates_from_request_and_use(self):
        rig = Rig()
        h = rig.request(correlation_id="corr-123")
        rig.use(h)
        self.assertEqual({e.correlation_id for e in rig.sink.events}, {"corr-123"})

    def test_make_event_sanitises_hostile_field_values(self):
        hostile = make_canary("bad value ", 20)
        ev = make_event(
            E.LEASE_DENIED,
            wall=datetime(2026, 1, 1, tzinfo=timezone.utc),
            outcome="denied",
            task_id=hostile,
            agent_id=hostile,
            run_id=hostile,
            correlation_id=hostile,
            lease_id=hostile,
            ref=hostile,
            reason_code=hostile,
        )
        self.assertNotIn(hostile, repr(ev.to_dict()))
        self.assertEqual(ev.task_id, "invalid")
        with self.assertRaises(ValueError):
            make_event(
                E.LEASE_DENIED,
                wall=datetime(2026, 1, 1, tzinfo=timezone.utc),
                outcome=hostile,
            )
        with self.assertRaises(ValueError):
            make_event(
                E.LEASE_DENIED, wall=datetime(2026, 1, 1), outcome="denied"
            )  # naive time

    def test_event_has_no_field_that_could_hold_free_text_or_values(self):
        self.assertNotIn("message", AUDIT_FIELDS)
        self.assertNotIn("value", AUDIT_FIELDS)
        self.assertEqual(len(AUDIT_FIELDS), 12)


class AuditCompleteness(unittest.TestCase):
    """T-30: every state change creates exactly one audit event; no event contains a canary."""

    def test_issue_use_expire_sequence(self):
        rig = Rig()
        h = rig.request(ttl=timedelta(minutes=1))
        self.assertEqual(types(rig), ["lease_requested", "lease_issued"])
        rig.use(h)
        rig.use(h)
        self.assertEqual(types(rig)[2:], ["lease_used", "lease_used"])
        rig.clock.advance(60)
        with self.assertRaises(Denied):
            rig.use(h)
        with self.assertRaises(Denied):
            rig.use(h)
        self.assertEqual(
            types(rig)[4:], ["lease_expired", "lease_denied", "lease_denied"]
        )
        self.assertEqual(len(rig.events(E.LEASE_EXPIRED)), 1)
        rig.broker.sweep()
        rig.broker.revoke_task("T-1", reason_code=RevokeReason.TASK_END)
        self.assertEqual(len(rig.events(E.LEASE_EXPIRED)), 1)
        self.assertEqual(
            len(rig.events(E.LEASE_REVOKED)), 0, "an expired lease is not revoked again"
        )

    def test_denial_has_requested_then_denied(self):
        rig = Rig()
        with self.assertRaises(Denied):
            rig.request(task="T-none")
        self.assertEqual(types(rig), ["lease_requested", "lease_denied"])
        self.assertEqual(rig.sink.events[-1].reason_code, "task_not_live")

    def test_revocation_has_exactly_one_event_per_lease(self):
        rig = Rig()
        rig.request(MODEL_REF)
        rig.request(SEARCH_REF)
        rig.registry.end_task("T-1", TaskState.COMPLETED, broker=rig.broker)
        rig.broker.revoke_task("T-1", reason_code=RevokeReason.TASK_END)
        self.assertEqual(len(rig.events(E.LEASE_REVOKED)), 2)
        self.assertEqual(len({e.lease_id for e in rig.events(E.LEASE_REVOKED)}), 2)

    def test_every_event_type_in_a_mixed_run_has_no_canary(self):
        rig = Rig(tasks=(("T-1", "R-1", "LR-06"), ("T-2", "R-2", "LR-04")))
        h = rig.request()
        rig.use(h)
        with self.assertRaises(Denied):
            rig.use(h, task_id="T-2")  # misuse
        rig.backend.set_healthy(False)
        with self.assertRaises(Denied):
            rig.request(SEARCH_REF)
        rig.backend.set_healthy(True)
        rig.clock.advance(3600)
        rig.broker.sweep()
        seen = {e.event_type for e in rig.sink.events}
        for needed in (
            "lease_requested",
            "lease_issued",
            "lease_used",
            "lease_denied",
            "lease_expired",
            "misuse_suspected",
            "backend_unhealthy",
        ):
            self.assertIn(needed, seen)
        text = rig.all_audit_text()
        for canary in rig.canaries.values():
            self.assertNotIn(canary, text)


class LoggingAllowList(unittest.TestCase):
    def setUp(self):
        self.stream = io.StringIO()
        self.handler = logging.StreamHandler(self.stream)
        self.handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
        self.logger = logging.getLogger(
            CREDENTIAL_LOGGER_NAME + "." + make_canary("t", 8)
        )
        self.logger.propagate = False
        self.logger.setLevel(logging.DEBUG)
        self.logger.addHandler(self.handler)
        self.filter = install_credential_log_filter(self.logger)
        self.canary = make_canary()

    def tearDown(self):
        self.logger.removeHandler(self.handler)

    def out(self):
        return self.stream.getvalue()

    def test_structured_event_logs_only_allow_listed_fields(self):
        log_credential_event(
            self.logger,
            "lease_issued",
            {
                "lease_id": "A" * 22,
                "agent_id": "LR-06",
                "task_id": "T-1",
                "token": self.canary,
                "prompt": self.canary,
                "api_key": self.canary,
                "headers": {"Authorization": self.canary},
                "ttl_s": 900,
            },
        )
        out = self.out()
        self.assertIn("lease_id=" + "A" * 22, out)
        self.assertIn("agent_id=LR-06", out)
        self.assertIn("ttl_s=900", out)
        for banned in (
            "token",
            "prompt",
            "api_key",
            "headers",
            "Authorization",
            self.canary,
        ):
            self.assertNotIn(banned, out)

    def test_invalid_shapes_are_replaced_not_logged(self):
        log_credential_event(
            self.logger,
            "lease_issued",
            {
                "agent_id": self.canary + " with spaces",
                "ref": self.canary,
                "ttl_s": self.canary,
                "reason_code": self.canary,
            },
        )
        out = self.out()
        self.assertNotIn(self.canary, out)
        self.assertEqual(out.count("invalid"), 4)

    def test_unknown_event_type_logs_nothing_but_its_name_class(self):
        log_credential_event(
            self.logger, "made_up_event", {"agent_id": "LR-06", "task_id": "T-1"}
        )
        self.assertNotIn("LR-06", self.out())
        self.assertIn("event_type=unknown", self.out())

    def test_free_form_records_on_credential_logger_are_dropped(self):
        self.logger.info("connecting with key %s", self.canary)
        self.logger.error(f"failed {self.canary}")
        self.logger.warning("x", extra={"secret": self.canary})
        try:
            raise RuntimeError(self.canary)
        except RuntimeError:
            self.logger.exception("boom")
        self.assertEqual(self.out(), "")
        self.assertEqual(self.filter.dropped, 4)

    def test_debug_level_does_not_widen_the_allow_list(self):
        for level in (logging.DEBUG, logging.INFO, logging.ERROR):
            self.stream.truncate(0)
            self.stream.seek(0)
            self.logger.setLevel(level)
            self.logger.debug("debug detail %s", self.canary)
            self.logger.log(logging.DEBUG, "x", extra={"password": self.canary})
            log_credential_event(
                self.logger, "lease_used", {"agent_id": "LR-06", "headers": self.canary}
            )
            self.assertNotIn(self.canary, self.out())
            self.assertNotIn("headers", self.out())

    def test_formatter_that_dumps_record_dict_cannot_leak_extras(self):
        class DumpAll(logging.Formatter):
            def format(self, record):
                return json.dumps({k: str(v) for k, v in record.__dict__.items()})

        self.handler.setFormatter(DumpAll())
        log_credential_event(self.logger, "lease_used", {"agent_id": "LR-06"})
        self.assertNotIn(self.canary, self.out())

    def test_audit_events_via_logging_sink_carry_no_value(self):
        rig = Rig()
        rig.broker.audit_sink = LoggingAuditSink(self.logger)
        h = rig.request()
        rig.use(h)
        out = self.out()
        self.assertIn("event_type=lease_issued", out)
        self.assertIn("purpose=model_inference", out)
        self.assertIn("environment=mock", out)
        self.assertNotIn(rig.canaries[MODEL_REF], out)

    def test_stream_audit_sink_writes_json_lines_with_contract_fields_only(self):
        rig = Rig()
        buf = io.StringIO()
        rig.broker.audit_sink = StreamAuditSink(buf)
        rig.request()
        lines = [json.loads(record) for record in buf.getvalue().splitlines()]
        self.assertEqual(
            [record["event_type"] for record in lines],
            ["lease_requested", "lease_issued"],
        )
        for record in lines:
            self.assertEqual(tuple(sorted(record)), tuple(sorted(AUDIT_FIELDS)))
        self.assertNotIn(rig.canaries[MODEL_REF], buf.getvalue())

    def test_allow_list_tables_are_consistent(self):
        for event_type, fields in EVENT_ALLOW_LIST.items():
            self.assertTrue(fields <= set(FIELD_SHAPES), event_type)
        for forbidden in (
            "prompt",
            "body",
            "headers",
            "token",
            "value",
            "password",
            "message",
            "env",
        ):
            for fields in EVENT_ALLOW_LIST.values():
                self.assertNotIn(forbidden, fields)
        self.assertEqual(allowed_fields("nope"), frozenset())


class TelemetryAllowList(unittest.TestCase):
    """T-18: a seeded value in a span attribute / exception / event is never exported."""

    def test_span_attributes_exception_and_events_never_export_the_canary(self):
        canary = make_canary()
        exported = []
        exporter = SafeSpanExporter(lambda name, attrs: exported.append((name, attrs)))
        try:
            raise RuntimeError(f"upstream rejected key {canary}")
        except RuntimeError as exc:
            exporter.record_span(
                "gateway.call",
                {
                    "agent_id": "LR-06",
                    "http.request.header.authorization": canary,
                    "db.connection_string": "postgres://u:" + canary + "@h/db",
                    "task_id": canary + " spaced",
                    "ttl_s": 900,
                    "prompt": canary,
                },
                exc=exc,
            )
        exporter.record_span(canary + "!bad name")
        text = repr(exported)
        self.assertNotIn(canary, text)
        name, attrs = exported[0]
        self.assertEqual(attrs["agent_id"], "LR-06")
        self.assertEqual(attrs["error_class"], "RuntimeError")
        self.assertEqual(attrs["task_id"], "invalid")
        self.assertEqual(set(attrs), {"agent_id", "task_id", "ttl_s", "error_class"})
        self.assertEqual(exported[1][0], "invalid")

    def test_exception_fields_never_include_message_args_or_cause(self):
        canary = make_canary()
        inner = ValueError(canary)
        try:
            try:
                raise inner
            except ValueError as e:
                raise KeyError(canary) from e
        except KeyError as outer:
            fields = exception_fields(outer)
        self.assertEqual(fields, {"error_class": "KeyError"})
        self.assertEqual(exception_fields(None), {})
        self.assertNotIn(
            canary, repr(sanitize_span_attributes({"error_class": canary + " x"}))
        )

    def test_broker_audit_events_through_exporter_path(self):
        rig = Rig()
        rig.request()
        exported = []
        exporter = SafeSpanExporter(lambda n, a: exported.append(a))
        for ev in rig.sink.events:
            exporter.record_span("lease.audit", ev.to_dict())
        self.assertNotIn(rig.canaries[MODEL_REF], repr(exported))
        self.assertTrue(all(e["task_id"] == "T-1" for e in exported))


if __name__ == "__main__":
    unittest.main()
