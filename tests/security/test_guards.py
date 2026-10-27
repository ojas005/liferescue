"""KAN-45 step 5 tests: sink guards (T-19 prompt, T-20 persistence, T-21 return path), log filter,
audit writer, telemetry with known values (T-18 final)."""

import io
import logging
import sqlite3
import unittest

from fixtures_broker import MODEL_REF, SEARCH_REF, Rig

from packages.secrets.audit import AuditEventType as E
from packages.secrets.codes import RequestReason
from packages.secrets.errors import SecretLeak
from packages.secrets.guards import RedactingAuditSink, RedactingLogFilter, SinkGuards
from packages.secrets.logging_rules import (
    CREDENTIAL_LOGGER_NAME,
    LoggingAuditSink,
    install_credential_log_filter,
)
from packages.secrets.secret_types import CredentialRequest
from packages.secrets.telemetry import SafeSpanExporter
from packages.secrets.testing import random_chars


class Base(unittest.TestCase):
    def setUp(self):
        self.rig = Rig(tasks=(("T-1", "R-1", "LR-06"),))
        self.rig.request()  # canary of MODEL_REF is now leased
        self.canary = self.rig.canaries[MODEL_REF]
        self.broker = self.rig.broker
        self.guards = SinkGuards(self.broker)

    def blocked_events(self):
        return self.rig.events(E.REDACTION_BLOCKED)


class PromptGuard(Base):
    def test_T19_prompt_with_leased_value_is_refused_event_emitted_no_retry(self):
        text = f"Please call the API using key {self.canary} and summarise"
        with self.assertRaises(SecretLeak) as ctx:
            self.guards.prompt(text)
        exc = ctx.exception
        self.assertEqual(exc.sink, "prompt")
        self.assertEqual(exc.kinds, ("secret",))
        self.assertNotIn(self.canary, str(exc) + repr(exc) + repr(exc.args))
        self.assertIsNone(exc.__cause__)
        events = self.blocked_events()
        self.assertEqual(len(events), 1)
        self.assertTrue(events[0].alert)
        self.assertEqual(events[0].reason_code, "prompt")
        self.assertNotIn(self.canary, self.rig.all_audit_text())
        # the same text is not accepted again, and does not double count
        with self.assertRaises(SecretLeak) as again:
            self.guards.prompt(text)
        self.assertEqual(again.exception.kinds, ("retry_of_blocked",))
        self.assertEqual(len(self.blocked_events()), 1)
        # a different, clean prompt goes through
        self.assertEqual(
            self.guards.prompt("summarise the incident"), "summarise the incident"
        )

    def test_T19_key_shaped_string_is_refused_even_if_never_leased(self):
        for prefix, n in (("xai-", 44), ("nvapi-", 56), ("tvly-", 30)):
            with self.subTest(prefix=prefix):
                with self.assertRaises(SecretLeak) as ctx:
                    self.guards.prompt("config: " + prefix + random_chars(n))
                self.assertEqual(len(ctx.exception.kinds), 1)

    def test_T19_structured_tool_result_with_nested_secret_is_refused(self):
        messages = [
            {
                "role": "tool",
                "content": [{"type": "text", "text": f"body: {self.canary}"}],
            }
        ]
        with self.assertRaises(SecretLeak):
            self.guards.prompt(messages)
        with self.assertRaises(SecretLeak):
            self.guards.prompt(
                {"headers": {"Authorization": "x"}}
            )  # denied key name with a value
        clean = [{"role": "tool", "content": "ok"}]
        self.assertEqual(self.guards.prompt(clean), clean)

    def test_T19_encoded_forms_are_refused_too(self):
        import base64

        with self.assertRaises(SecretLeak):
            self.guards.prompt(
                "data:" + base64.b64encode(self.canary.encode()).decode()
            )
        with self.assertRaises(SecretLeak):
            self.guards.prompt(self.canary[:10] + "\n" + self.canary[10:])

    def test_broker_assert_safe_to_emit_and_redact_api(self):
        with self.assertRaises(SecretLeak) as ctx:
            self.broker.assert_safe_to_emit(f"x {self.canary}", sink="log")
        self.assertEqual(ctx.exception.sink, "log")
        self.broker.assert_safe_to_emit("clean text", sink="log")
        with self.assertRaises(SecretLeak) as ctx:
            self.broker.assert_safe_to_emit(
                self.canary, sink=self.canary
            )  # hostile sink name is not echoed
        self.assertEqual(ctx.exception.sink, "unknown")
        self.assertNotIn(self.canary, str(ctx.exception))
        self.assertEqual(
            self.broker.redact(f"a {self.canary} b"), "a [REDACTED:secret] b"
        )

    def test_blocked_digest_memory_is_bounded(self):
        guards = SinkGuards(self.broker, max_blocked_digests=3)
        for i in range(10):
            with self.assertRaises(SecretLeak):
                guards.prompt(f"{i} {self.canary}")
        self.assertLessEqual(len(guards._blocked), 3)


class PersistenceGuard(Base):
    def test_T20_write_with_canary_refused_writer_not_called(self):
        written = []
        for record in (
            {"run_id": "R-1", "state": {"note": f"tool said {self.canary}"}},
            {"run_id": "R-1", "api_key": "anything"},
            {self.canary: "value-as-key"},
            {
                "steps": [
                    {
                        "args": {
                            "conn": "postgres://u:"
                            + random_chars(20)
                            + "@h.example.invalid/db"
                        }
                    }
                ]
            },
        ):
            with self.subTest(record=list(record)[:2]):
                with self.assertRaises(SecretLeak) as ctx:
                    self.guards.persist(record, written.append)
                self.assertEqual(ctx.exception.sink, "persistence")
        self.assertEqual(written, [])
        self.assertEqual(len(self.blocked_events()), 4)
        self.assertNotIn(self.canary, self.rig.all_audit_text())

    def test_T20_clean_record_is_written_and_unknown_objects_are_refused(self):
        written = []
        rec = {
            "run_id": "R-1",
            "step": 3,
            "state": {"phase": "planning", "lease": "A" * 22},
        }
        self.guards.persist(rec, written.append)
        self.assertEqual(written, [rec])
        with self.assertRaises(SecretLeak):
            self.guards.persist({"obj": object()}, written.append)
        self.assertEqual(len(written), 1)

    def test_T20_real_database_dump_holds_no_canary(self):
        db = sqlite3.connect(":memory:")
        db.execute("create table checkpoints (run_id text, state text)")

        def write(rec):
            db.execute(
                "insert into checkpoints values (?, ?)", (rec["run_id"], rec["state"])
            )

        self.guards.persist({"run_id": "R-1", "state": "planning"}, write)
        with self.assertRaises(SecretLeak):
            self.guards.persist({"run_id": "R-1", "state": f"key={self.canary}"}, write)
        dump = "\n".join(db.iterdump())
        self.assertNotIn(self.canary, dump)
        self.assertIn("planning", dump)
        db.close()


class ReturnPathAndOutgoing(Base):
    def test_T21_provider_error_body_with_canary_reaches_agent_redacted(self):
        class ProviderError(Exception):
            pass

        def call():
            try:
                raise ConnectionError(f"TLS failed for {self.canary}")
            except ConnectionError as inner:
                raise ProviderError(
                    f'HTTP 401 {{"error": "invalid key {self.canary}"}}'
                ) from inner

        result = self.guards.run_provider_call(call)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_class"], "ProviderError")
        self.assertNotIn(self.canary, repr(result))
        self.assertIn("[REDACTED:secret]", result["error"])

    def test_T21_success_result_is_redacted_including_denied_keys(self):
        result = self.guards.run_provider_call(
            lambda: {
                "echo": f"you sent {self.canary}",
                "headers": {"set-cookie": "sid=abc"},
                "n": 1,
            }
        )
        self.assertTrue(result["ok"])
        self.assertNotIn(self.canary, repr(result))
        self.assertEqual(result["result"]["headers"]["set-cookie"], "[REDACTED:field]")
        self.assertEqual(result["result"]["n"], 1)

    def test_outgoing_text_helpers_refuse_secrets(self):
        with self.assertRaises(SecretLeak):
            self.guards.outgoing(f"PR comment: the key is {self.canary}")
        with self.assertRaises(SecretLeak):
            self.guards.outgoing("Jira: " + "xai-" + random_chars(44))
        self.assertEqual(self.guards.outgoing("Looks good to me"), "Looks good to me")
        self.assertEqual(len(self.blocked_events()), 2)


class LogFilterAndAudit(Base):
    def test_general_log_filter_redacts_message_args_extras_and_tracebacks(self):
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(logging.Formatter("%(message)s"))
        handler.addFilter(RedactingLogFilter(self.broker.redactor))
        logger = logging.getLogger("kan45.test_guards." + random_chars(6))
        logger.propagate = False
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        logger.info("key %s and %s", self.canary, {"password": "hunter2hunter2"})
        try:
            raise RuntimeError(f"bad {self.canary}")
        except RuntimeError:
            logger.exception("failed")
        logger.error("stack", stack_info=True, extra={"note": self.canary})
        out = stream.getvalue()
        self.assertNotIn(self.canary, out)
        self.assertNotIn("hunter2hunter2", out)
        self.assertGreaterEqual(out.count("[REDACTED:secret]"), 2)

    def test_n04_tuple_args_are_kept_for_access_style_formatters(self):
        # LR 08 N-04: uvicorn.access unpacks record.args (5-tuple); the filter must keep the tuple.
        flt = RedactingLogFilter(self.broker.redactor)
        record = logging.LogRecord(
            "uvicorn.access",
            logging.INFO,
            "p",
            1,
            '%s - "%s %s HTTP/%s" %d',
            ("127.0.0.1:5", "GET", f"/x?k={self.canary}", "1.1", 200),
            None,
        )
        self.assertTrue(flt.filter(record))
        self.assertIsInstance(record.args, tuple)
        self.assertEqual(len(record.args), 5)
        self.assertEqual((record.args[1], record.args[4]), ("GET", 200))
        self.assertNotIn(self.canary, record.getMessage())
        self.assertIn("[REDACTED", record.getMessage())

    def test_unformattable_log_message_is_dropped_not_raised(self):
        flt = RedactingLogFilter(self.broker.redactor)
        record = logging.LogRecord(
            "n", logging.INFO, "p", 1, "bad %d format", ("x",), None
        )
        self.assertTrue(flt.filter(record))
        self.assertNotIn("bad", record.msg)

    def test_audit_writer_scrubs_a_leased_value_that_ended_up_in_an_id_field(self):
        # simulate a bug that puts a leased value where an id belongs: the shape check alone would allow it
        self.rig.registry.register(self.canary, "R-9", "LR-06")
        self.broker.request(
            CredentialRequest(
                task_id=self.canary,
                run_id="R-9",
                agent_id="LR-06",
                ref=SEARCH_REF,
                reason_code=RequestReason.WEB_SEARCH_CALL,
            )
        )
        text = self.rig.all_audit_text()
        self.assertNotIn(self.canary, text)
        self.assertIn("'task_id': 'redacted'", text)

    def test_T18_final_known_value_in_allowed_telemetry_and_log_fields_is_scrubbed(
        self,
    ):
        exported = []
        exporter = SafeSpanExporter(
            lambda n, a: exported.append((n, a)),
            leak_check=self.broker.redactor.contains_secret,
        )
        exporter.record_span(
            "gateway.call", {"agent_id": self.canary, "task_id": "T-1"}
        )
        exporter.record_span(self.canary)
        self.assertNotIn(self.canary, repr(exported))
        self.assertEqual(exported[0][1]["agent_id"], "redacted")
        self.assertEqual(exported[1][0], "redacted")

        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        logger = logging.getLogger(CREDENTIAL_LOGGER_NAME + ".t18." + random_chars(6))
        logger.propagate = False
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        install_credential_log_filter(logger)
        self.broker.audit_sink = RedactingAuditSink(
            LoggingAuditSink(logger), self.broker.redactor
        )
        self.rig.registry.register(self.canary, "R-9", "LR-06")
        self.broker.request(
            CredentialRequest(
                task_id=self.canary,
                run_id="R-9",
                agent_id="LR-06",
                ref=SEARCH_REF,
                reason_code=RequestReason.WEB_SEARCH_CALL,
            )
        )
        self.assertNotIn(self.canary, stream.getvalue())
        self.assertIn("task_id=redacted", stream.getvalue())

    def test_audit_sink_attribute_passthrough_for_local_sinks(self):
        self.assertTrue(
            self.broker.audit_sink.events
        )  # RedactingAuditSink exposes the inner InMemoryAuditSink API


if __name__ == "__main__":
    unittest.main()
