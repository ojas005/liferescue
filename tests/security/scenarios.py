"""Seeded-canary leak scenarios shared by T-16, T-23 and the negative control T-24 (not a test module).

``emit_through_sinks`` pushes one canary through every product sink in every form the spec lists
(log call, exception message, nested dict, URL, header, base64, split across lines, ...) and returns
what each sink produced. ``leaks_in`` is an INDEPENDENT checker (it does not use the product's variant
generator): a literal search for the canary and its encodings.
"""
import base64
import io
import json
import logging
from urllib.parse import quote, quote_plus

from packages.secrets.guards import RedactingLogFilter


def encodings_of(canary: str) -> dict:
    raw = canary.encode()
    half = len(canary) // 2
    return {
        "raw": canary,
        "base64": base64.b64encode(raw).decode(),
        "base64_nopad": base64.b64encode(raw).decode().rstrip("="),
        "base64_urlsafe": base64.urlsafe_b64encode(raw).decode().rstrip("="),
        "url_quoted": quote(canary, safe=""),
        "url_quote_plus": quote_plus(canary),
        "hex": raw.hex(),
        "json_escaped": json.dumps(canary)[1:-1],
        "first_half": canary[:half] if len(canary[:half]) >= 12 else canary,
    }


def leaks_in(output: str, canary: str) -> list:
    """Names of the canary forms found literally in ``output`` (empty list = clean)."""
    out = []
    for name, form in encodings_of(canary).items():
        if name == "first_half":
            continue  # prefix is checked separately below to avoid matching the visible 'mock-' marker
        if form and form in output:
            out.append(name)
    tail = canary[8:]  # the random part (after the visible non-secret prefix)
    if len(tail) >= 16 and tail in output:
        out.append("random_part")
    return out


def emit_through_sinks(rig_or_broker, canary: str) -> dict:
    """Route ``canary`` through each sink with the product's redaction ON. Returns {scenario: text}."""
    broker = getattr(rig_or_broker, "broker", rig_or_broker)
    redactor = broker.redactor
    guards = SinkGuardsFactory.for_broker(broker)
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
    handler.addFilter(RedactingLogFilter(redactor))
    logger = logging.getLogger("kan45.scenarios." + str(id(stream)))
    logger.propagate = False
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)

    class Keep(logging.Handler):
        """Keeps what a structured-log formatter (one that dumps record attributes) would see."""

        def __init__(self):
            super().__init__()
            self.dumped = ""
            self.addFilter(RedactingLogFilter(redactor))

        def emit(self, record):
            self.dumped = repr({k: v for k, v in record.__dict__.items() if k not in ("args",)})

    keep = Keep()
    logger.addHandler(keep)

    out = {}

    def captured(fn):
        stream.seek(0)
        stream.truncate(0)
        fn()
        return stream.getvalue()

    out["log_call"] = captured(lambda: logger.info("calling provider with key %s", canary))
    out["log_fstring"] = captured(lambda: logger.warning(f"key={canary}"))
    captured(lambda: logger.info("x", extra={"payload": {"note": canary, "password": canary}}))
    out["log_extra_record_dump"] = keep.dumped

    def log_exc():
        try:
            raise RuntimeError(f"upstream 401 for credential {canary}")
        except RuntimeError:
            logger.exception("provider call failed")

    out["log_exception"] = captured(log_exc)
    try:
        try:
            raise ValueError(f"inner {canary}")
        except ValueError as inner:
            raise KeyError("outer") from inner
    except KeyError as exc:
        out["error_handler_chain"] = redactor.redact_exception(exc, sink="error")
        out["traceback"] = redactor.format_traceback(exc)
    out["nested_dict"] = json.dumps(redactor.redact({"a": [{"b": f"x {canary} y", "c": (canary,)}], "d": {"e": {"f": canary}}}))
    out["url_query"] = redactor.redact_text(f"https://api.example.invalid/v1/chat?foo=1&bar={canary}&baz=2")
    out["url_userinfo"] = redactor.redact_text(f"postgres://svc:{canary}@db.example.invalid:5432/app")
    out["header_authorization"] = json.dumps(redactor.redact({"Authorization": f"Bearer {canary}", "X-Request": f"id {canary}"}))
    out["header_text"] = redactor.redact_text(f"GET / HTTP/1.1\nAuthorization: Bearer {canary}\nCookie: sid={canary}\n")
    out["base64"] = redactor.redact_text("blob=" + base64.b64encode(canary.encode()).decode())
    out["base64_embedded"] = redactor.redact_text("cfg=" + base64.b64encode(b"prefix-bytes:" + canary.encode() + b":suffix").decode())
    out["base64_urlsafe"] = redactor.redact_text(base64.urlsafe_b64encode(canary.encode()).decode().rstrip("="))
    out["url_encoded"] = redactor.redact_text("q=" + quote(canary, safe="") + "&r=" + quote_plus(canary))
    out["hex"] = redactor.redact_text(canary.encode().hex())
    out["json_text"] = redactor.redact_text(json.dumps({"k": canary}))
    a, b, c = canary[:9], canary[9:19], canary[19:]
    out["split_lines"] = redactor.redact_text(f"{a}\n{b}\n  {c}")
    out["split_concat"] = redactor.redact_text(f'"{a}" + "{b}" + "{c}"')
    out["split_backslash"] = redactor.redact_text(f"{a}\\\n{b}\\\n{c}")
    out["return_path"] = repr(guards.return_path({"error": f"provider said bad key {canary}", "headers": {"x-api-key": canary}}))
    out["provider_error"] = repr(guards.run_provider_call(lambda: (_ for _ in ()).throw(RuntimeError(f"HTTP 401 body: key {canary} rejected"))))
    return out


class SinkGuardsFactory:
    @staticmethod
    def for_broker(broker):
        from packages.secrets.guards import SinkGuards

        return SinkGuards(broker)
