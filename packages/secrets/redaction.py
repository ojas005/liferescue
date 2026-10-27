"""Redaction library (KAN-45 spec section 6, step 5).

Principle: prevent by type and construction first (SecretValue, handles), redact second, scan third.
This module is the second layer. It provides:

  * known-value redaction: exact occurrences of the currently leased values AND common encodings
    (base64 in all three alignments, URL-encoding, JSON/Python escapes, HTML escapes, hex, and the
    value split by whitespace / line breaks / quote concatenation) become ``[REDACTED:secret]``;
  * pattern redaction: key-shaped strings become ``[REDACTED:<kind>]``; the patterns come from ONE
    source file, ``patterns.json``, which a parity test (T-22) compares with ``.gitleaks.toml``;
  * the key-name rule for structured data: values under keys such as ``password`` or ``token``
    become ``[REDACTED:field]`` whatever they look like;
  * exception/traceback redaction including chained causes.

No partial reveal (spec 6.5): never a prefix, suffix, length or hash of a secret. The only marker is
``[REDACTED:<kind>]``.
"""

from __future__ import annotations

import base64
import datetime as _dt
import decimal
import enum
import html
import json
import re
import traceback
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional
from urllib.parse import quote, quote_plus

from .errors import ConfigurationError
from .leased_values import LeasedValues
from .secret_types import SecretValue

PATTERNS_PATH = Path(__file__).with_name("patterns.json")

SECRET_KIND = "secret"
FIELD_KIND = "field"
OBJECT_KIND = "object"

#: Mapping keys whose values are always redacted (spec 6.4). Matched case-insensitively as substrings
#: of the key after normalising "-", " " and "." to "_" (so "X-Api-Key" and "dbPassword" are caught).
DENIED_KEY_TERMS = (
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "set_cookie",
    "private_key",
    "credential",
    "connection_string",
)

#: Known-value variants other than the exact value are only generated for values at least this long
#: (a 3-character "secret" split/encoded would redact half the text). Exact matches always apply.
MIN_VARIANT_LEN = 8
MAX_SPLIT_LEN = 512
MAX_DEPTH = 20
MAX_TEXT = 5_000_000


_SCALAR_TEXT_TYPES = (
    _dt.datetime,
    _dt.date,
    _dt.time,
    _dt.timedelta,
    decimal.Decimal,
    uuid.UUID,
)


def marker(kind: str) -> str:
    return f"[REDACTED:{kind}]"


# ------------------------------------------------------------------------------- patterns --------
@dataclass(frozen=True)
class PatternRule:
    rule_id: str
    kind: str
    regex: "re.Pattern[str]"
    group: int
    gitleaks_rule: Optional[str]
    allow_match: tuple  # compiled regexes; a match whose text matches any of these is NOT redacted


class PatternSet:
    def __init__(self, rules: Iterable[PatternRule]) -> None:
        self.rules = tuple(rules)

    @classmethod
    def from_mapping(cls, doc: Any) -> "PatternSet":
        if (
            not isinstance(doc, Mapping)
            or doc.get("version") != 1
            or not isinstance(doc.get("rules"), list)
        ):
            raise ConfigurationError("patterns file has the wrong shape")
        rules, seen = [], set()
        for item in doc["rules"]:
            if not isinstance(item, Mapping):
                raise ConfigurationError("pattern rule must be a mapping")
            try:
                rule_id, kind, regex, group = (
                    item["id"],
                    item["kind"],
                    item["regex"],
                    item["group"],
                )
                compiled = re.compile(regex)
                allow = tuple(
                    re.compile(a) for a in item.get("allow_match_regexes", [])
                )
            except (KeyError, re.error, TypeError):
                raise ConfigurationError("pattern rule invalid") from None
            if (
                not isinstance(rule_id, str)
                or rule_id in seen
                or not re.fullmatch(r"[a-z0-9_]{1,40}", str(kind))
            ):
                raise ConfigurationError("pattern rule id/kind invalid")
            if (
                not isinstance(group, int)
                or isinstance(group, bool)
                or not 0 <= group <= compiled.groups
            ):
                raise ConfigurationError("pattern rule group invalid")
            seen.add(rule_id)
            rules.append(
                PatternRule(
                    rule_id, kind, compiled, group, item.get("gitleaks_rule"), allow
                )
            )
        return cls(rules)

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "PatternSet":
        target = Path(path) if path is not None else PATTERNS_PATH
        doc = None
        failed = False
        try:
            doc = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            failed = True
        if failed:
            raise ConfigurationError("patterns file unreadable or invalid")
        return cls.from_mapping(doc)

    def scanner_mirrored(self) -> "PatternSet":
        """Only the rules that mirror a ``.gitleaks.toml`` rule (what the CI scanner would flag)."""
        return PatternSet(r for r in self.rules if r.gitleaks_rule)

    def spans(self, text: str) -> list:
        out = []
        for rule in self.rules:
            for m in rule.regex.finditer(text):
                if any(a.search(m.group(0)) for a in rule.allow_match):
                    continue
                start, end = m.span(rule.group)
                if start < end:
                    out.append((start, end, rule.kind))
        return out


# ------------------------------------------------------------------------- known values ---------
def base64_variants(data: bytes) -> set:
    """Substrings of the base64 text of ``data`` that stay stable wherever ``data`` sits in a larger buffer.

    For each of the 3 byte alignments, leading characters that mix in unknown preceding bytes and
    trailing characters that mix in unknown following bytes are dropped. Standard and URL-safe alphabets.
    """
    out = set()
    lead_drop = (0, 2, 3)
    for offset in range(3):
        padded = b"\x00" * offset + data
        enc = base64.b64encode(padded).decode("ascii").rstrip("=")
        trail = 0 if len(padded) % 3 == 0 else 1
        core = enc[lead_drop[offset] : len(enc) - trail]
        if len(core) >= MIN_VARIANT_LEN:
            out.add(core)
            out.add(core.replace("+", "-").replace("/", "_"))
    return out


def value_variants(value: str) -> set:
    """Exact text forms of ``value`` (plain-string search)."""
    forms = {value}
    if len(value) < MIN_VARIANT_LEN:
        return forms
    data = value.encode("utf-8")
    forms |= base64_variants(data)
    for q in (quote(value, safe=""), quote_plus(value)):
        forms.add(q)
        forms.add(re.sub(r"%[0-9A-F]{2}", lambda m: m.group(0).lower(), q))
    forms.add(json.dumps(value)[1:-1])
    forms.add(json.dumps(value, ensure_ascii=False)[1:-1])
    forms.add(repr(value)[1:-1])
    forms.add(value.encode("unicode_escape").decode("ascii"))
    forms.add(html.escape(value, quote=True))
    forms.add(data.hex())
    forms.add(data.hex().upper())
    forms.add(
        re.sub(r"([^A-Za-z0-9])", r"\\\1", value)
    )  # backslash-escaped punctuation
    return {f for f in forms if f}


def split_regex(value: str) -> Optional["re.Pattern[str]"]:
    """Regex matching ``value`` with whitespace, line breaks, backslashes, quotes or '+' between characters."""
    if len(value) < MIN_VARIANT_LEN or len(value) > MAX_SPLIT_LEN:
        return None
    sep = r"[\s\\\"'+]*"
    return re.compile(sep.join(re.escape(ch) for ch in value))


class KnownValueMatcher:
    """Matches a fixed set of secret values and their encodings. Rebuilt when the set changes."""

    def __init__(self, values: Iterable[str]) -> None:
        self.key = tuple(sorted(set(values)))
        forms = set()
        for v in self.key:
            forms |= value_variants(v)
        ordered = sorted(
            forms, key=len, reverse=True
        )  # longest first so partial overlaps lose
        self._literal = (
            re.compile("|".join(re.escape(f) for f in ordered)) if ordered else None
        )
        self._split = [r for r in (split_regex(v) for v in self.key) if r is not None]

    def spans(self, text: str) -> list:
        out = []
        if self._literal is not None:
            out.extend(
                (m.start(), m.end(), SECRET_KIND) for m in self._literal.finditer(text)
            )
        for rx in self._split:
            out.extend((m.start(), m.end(), SECRET_KIND) for m in rx.finditer(text))
        return out


def _merge(spans: list) -> list:
    """Merge overlapping spans; the kind of the span that starts first (then the longer) wins."""
    spans = sorted(spans, key=lambda s: (s[0], -(s[1] - s[0])))
    merged: list = []
    for start, end, kind in spans:
        if merged and start < merged[-1][1]:
            prev = merged[-1]
            merged[-1] = (prev[0], max(prev[1], end), prev[2])
        else:
            merged.append((start, end, kind))
    return merged


# ----------------------------------------------------------------------------- redactor ----------
class Redactor:
    """Redacts text, structures and exceptions. Thread-safe for concurrent use."""

    def __init__(
        self,
        leased_values: Optional[LeasedValues] = None,
        *,
        patterns: Optional[PatternSet] = None,
        metrics=None,
        key_exempt: Iterable[str] = (),
        extra_values: Iterable[str] = (),
    ) -> None:
        self._leased = leased_values
        self._patterns = patterns if patterns is not None else PatternSet.load()
        self._metrics = metrics
        self._exempt = frozenset(
            self._norm_key(k) for k in key_exempt
        )  # explicit, reviewed exemptions only
        self._extra = tuple(extra_values)
        self._matcher = KnownValueMatcher(())

    # ---- key-name rule ----
    @staticmethod
    def _norm_key(key: str) -> str:
        key = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", key)  # camelCase -> camel_Case
        return re.sub(r"[-\s.]+", "_", key).lower()

    def is_denied_key(self, key: Any) -> bool:
        if not isinstance(key, str):
            return False
        norm = self._norm_key(key)
        if norm in self._exempt:
            return False
        return any(term in norm for term in DENIED_KEY_TERMS)

    # ---- known values ----
    def _current_matcher(self) -> KnownValueMatcher:
        values = list(self._extra)
        if self._leased is not None:
            values.extend(self._leased._raw_values())
        key = tuple(sorted(set(values)))
        if key != self._matcher.key:
            self._matcher = KnownValueMatcher(key)
        return self._matcher

    # ---- text ----
    def _spans(self, text: str) -> list:
        return _merge(self._current_matcher().spans(text) + self._patterns.spans(text))

    def find_leaks(self, text: str) -> tuple:
        """Sorted unique kinds of secrets found in ``text`` (empty tuple if clean)."""
        if not isinstance(text, str):
            return ()
        if len(text) > MAX_TEXT:
            return ("oversize",)  # fail closed: too large to scan
        return tuple(sorted({kind for _, _, kind in self._spans(text)}))

    def contains_secret(self, text: Any) -> bool:
        return isinstance(text, str) and bool(self.find_leaks(text))

    def redact_text(self, text: str, *, sink: str = "unknown") -> str:
        if not isinstance(text, str):
            raise TypeError("redact_text expects str")
        if len(text) > MAX_TEXT:
            self._count("oversize", sink)
            return marker("oversize")  # fail closed
        spans = self._spans(text)
        if not spans:
            return text
        out, pos = [], 0
        for start, end, kind in spans:
            out.append(text[pos:start])
            out.append(marker(kind))
            self._count(kind, sink)
            pos = end
        out.append(text[pos:])
        return "".join(out)

    # ---- structures ----
    def redact(
        self,
        obj: Any,
        *,
        sink: str = "unknown",
        _depth: int = 0,
        _seen: Optional[set] = None,
    ) -> Any:
        """Deep-copy ``obj`` with secrets removed. Mapping keys matching the key-name rule have their
        whole value replaced by ``[REDACTED:field]``. Unknown object types become ``[REDACTED:object]``."""
        if _depth > MAX_DEPTH:
            return marker("depth")
        if obj is None or isinstance(obj, (bool, int, float)):
            return obj
        if isinstance(obj, str):
            return self.redact_text(obj, sink=sink)
        if isinstance(obj, (bytes, bytearray)):
            return self.redact_text(bytes(obj).decode("utf-8", "replace"), sink=sink)
        if isinstance(obj, SecretValue):
            self._count(SECRET_KIND, sink)
            return marker(SECRET_KIND)
        if isinstance(obj, enum.Enum):
            return self.redact(obj.value, sink=sink, _depth=_depth + 1, _seen=_seen)
        if isinstance(obj, _SCALAR_TEXT_TYPES):
            return self.redact_text(str(obj), sink=sink)
        seen = _seen if _seen is not None else set()
        if id(obj) in seen:
            return marker("cycle")
        if isinstance(obj, Mapping):
            seen = seen | {id(obj)}
            out = {}
            for key, value in obj.items():
                safe_key = (
                    self.redact_text(key, sink=sink)
                    if isinstance(key, str)
                    else self.redact(key, sink=sink, _depth=_depth + 1, _seen=seen)
                )
                if self.is_denied_key(key):
                    self._count(FIELD_KIND, sink)
                    out[safe_key] = marker(FIELD_KIND)
                else:
                    out[safe_key] = self.redact(
                        value, sink=sink, _depth=_depth + 1, _seen=seen
                    )
            return out
        if isinstance(obj, (list, tuple, set, frozenset)):
            seen = seen | {id(obj)}
            items = [
                self.redact(v, sink=sink, _depth=_depth + 1, _seen=seen) for v in obj
            ]
            return (
                items
                if isinstance(obj, list)
                else tuple(items)
                if isinstance(obj, tuple)
                else items
            )
        if isinstance(obj, BaseException):
            return self.redact_exception(obj, sink=sink)
        self._count(OBJECT_KIND, sink)
        return marker(OBJECT_KIND)

    def find_leaks_in(
        self, obj: Any, *, _depth: int = 0, _seen: Optional[set] = None
    ) -> tuple:
        """Kinds of secrets found anywhere in a structure (keys, values, denied key names)."""
        kinds: set = set()
        self._scan(obj, kinds, 0, set())
        return tuple(sorted(kinds))

    def _scan(self, obj: Any, kinds: set, depth: int, seen: set) -> None:
        if depth > MAX_DEPTH:
            kinds.add("depth")
            return
        if isinstance(obj, str):
            kinds.update(self.find_leaks(obj))
        elif isinstance(obj, (bytes, bytearray)):
            kinds.update(self.find_leaks(bytes(obj).decode("utf-8", "replace")))
        elif isinstance(obj, SecretValue):
            kinds.add(SECRET_KIND)
        elif isinstance(obj, enum.Enum):
            self._scan(obj.value, kinds, depth + 1, seen)
        elif isinstance(obj, _SCALAR_TEXT_TYPES):
            kinds.update(self.find_leaks(str(obj)))
        elif obj is None or isinstance(obj, (bool, int, float)):
            return
        elif id(obj) in seen:
            kinds.add("cycle")
        elif isinstance(obj, Mapping):
            seen = seen | {id(obj)}
            for key, value in obj.items():
                if isinstance(key, str):
                    kinds.update(self.find_leaks(key))
                if self.is_denied_key(key) and value not in (None, "", 0, False):
                    kinds.add(FIELD_KIND)
                self._scan(value, kinds, depth + 1, seen)
        elif isinstance(obj, (list, tuple, set, frozenset)):
            seen = seen | {id(obj)}
            for v in obj:
                self._scan(v, kinds, depth + 1, seen)
        elif isinstance(obj, BaseException):
            kinds.update(self.find_leaks(self.redact_exception_raw_text(obj)))
        else:
            kinds.add(
                OBJECT_KIND
            )  # unknown object types cannot be inspected: treated as unsafe

    # ---- exceptions ----
    @staticmethod
    def redact_exception_raw_text(exc: BaseException, max_chain: int = 6) -> str:
        parts, seen, cur = [], set(), exc
        while cur is not None and id(cur) not in seen and len(parts) < max_chain:
            seen.add(id(cur))
            try:
                args = " ".join(str(a) for a in cur.args)
            except Exception:
                args = ""
            parts.append(f"{type(cur).__name__}: {args}")
            cur = cur.__cause__ or cur.__context__
        return "; caused by ".join(parts)

    def redact_exception(self, exc: BaseException, *, sink: str = "unknown") -> str:
        """``ClassName: message`` for the exception and its chain, with secrets removed."""
        return self.redact_text(self.redact_exception_raw_text(exc), sink=sink)

    def format_traceback(self, exc: BaseException, *, sink: str = "log") -> str:
        text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        return self.redact_text(text, sink=sink)

    # ---- metrics ----
    def _count(self, kind: str, sink: str) -> None:
        if self._metrics is not None:
            self._metrics.inc(
                "redactions", f"{kind}:{sink}"
            )  # counts by kind and sink only, never content
