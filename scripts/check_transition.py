#!/usr/bin/env python3
"""Jira transition allowlist validator (KAN-20, WI-04-6). Pure logic, fail closed.

Decides whether a status change (or a status-unchanged BLOCKED note) on a KAN Jira issue is
allowed for an actor, according to the machine-readable allowlist
scripts/jira-transition-allowlist.json (ADR-0017 status mapping, approved by Ojas Sharma on
2026-10-04 07:28 IST: existing four statuses only; BLOCKED/REWORK are labels/comments; agents may
move work to In Progress / In Review per evidence; an agent never declares its own work Done).

What this module does NOT do: it never calls Jira, GitHub or any network service, never starts a
process and never evaluates input. It checks the SHAPE of the evidence it is given (for example
"this is an https URL"); it cannot know whether the evidence is true. A human or reviewer still
has to read it. Labels and comments are free text in Jira and are never used to grant a permission:
a label can only add requirements (for example the rework path) or be required, never unlock a
transition.

The checker TRUSTS the caller-declared actor_type: it is a consistency check on what the caller says,
NOT access control. Anyone who can call it can claim to be "human". KAN-26 must derive the actor
type from an authenticated identity (never from request text) before it calls this module.

Everything fails closed: unknown status/actor/transition, malformed input, unknown evidence
fields, missing or malformed evidence, a missing comment and an invalid allowlist file all give
"deny". Python standard library only.

Command line:
  python3 scripts/check_transition.py --validate-allowlist            # check the data file itself
  python3 scripts/check_transition.py --request request.json          # check one request (JSON file)
Exit code 0 = allow / valid, 1 = deny / invalid, 2 = usage error.
"""

import argparse
import collections
import importlib.util
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ALLOWLIST_PATH = os.path.join(HERE, "jira-transition-allowlist.json")
BRANCH_VALIDATOR_PATH = os.path.join(HERE, "check-branch-name.py")

# Hard-coded guard constants, deliberately NOT read from the data file, so that a tampered or
# mistaken data file can never let a non-human actor reach Done (defence in depth).
HUMAN_ACTOR = "human"
HUMAN_ONLY_STATUSES = frozenset({"Done"})
# The rework label may only be added or removed by these transitions (P5-2), whatever the data file says.
REWORK_LABEL = "exec-rework"
REWORK_LABEL_TRANSITIONS = frozenset(
    {"send_to_rework", "complete_rework", "return_to_todo", "reopen"}
)

MAX_COMMENT = 1000
MAX_TEXT = 500
MAX_URL = 2048
MAX_LABELS = 50
MAX_FILE_BYTES = 262144
MAX_FIELD_VALUE = (
    300  # longest value of a `key: value` field inside a REWORK:/BLOCKED: comment
)

_BRANCH_MODULE = None  # branch-name validator, loaded on first use

Decision = collections.namedtuple("Decision", ["allowed", "transition_id", "reasons"])

_URL = re.compile(
    r"^https://[A-Za-z0-9][A-Za-z0-9.-]{0,252}(:[0-9]{1,5})?"
    r"(/[A-Za-z0-9._~%+=:@/-]*)?"
    r"(\?[A-Za-z0-9._~%+=:@/&?,-]*)?"
    r"(#[A-Za-z0-9._~%+=:@/&?,-]*)?$"
)
_DOMAIN_LABEL = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
_TLD = re.compile(r"^(?:[A-Za-z]{2,63}|xn--[A-Za-z0-9-]{1,59})$")
_LABEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")
_NAME = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
_COMMENT_KEY = re.compile(r"^[a-z][a-z ]{0,31}$")
_COMMENT_FIELD_TYPES = ("actor", "text", "url")
_FIELD = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_STATUS = re.compile(r"^[A-Za-z][A-Za-z ]{0,31}$")
_ACTOR_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.@-]{0,63}$")
_EVIDENCE_TYPES = ("text", "url", "branch", "true", "bool")
_ACTOR_KINDS = ("human", "agent", "automation")

_TOP_KEYS = {
    "schema_version",
    "title",
    "approval",
    "sources",
    "statuses",
    "human_only_statuses",
    "actor_types",
    "labels",
    "assertion_label_words",
    "assertion_markers",
    "evidence_fields",
    "transitions",
    "rework_lifecycle",
    "status_unchanged_events",
    "evidence_url_hosts",
}
_TOP_KEYS_OPTIONAL = {
    "evidence_url_hosts"
}  # optional host allowlist; absent or [] = off
_TRANSITION_KEYS = {
    "id",
    "from",
    "to",
    "actors",
    "approval",
    "proposed_assumptions",
    "evidence_requirements",
    "when_labels_before_include",
    "when_labels_before_exclude",
    "labels_after_include",
    "labels_after_exclude",
    "comment_requirement",
    "conditional_comment_requirements",
}
_TRANSITION_REQUIRED = {
    "id",
    "from",
    "to",
    "actors",
    "approval",
    "proposed_assumptions",
    "evidence_requirements",
}
_EVENT_KEYS = {
    "id",
    "statuses",
    "actors",
    "comment_requirement",
    "approval",
    "proposed_assumptions",
}


# ---------------------------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------------------------


def _is_str_list(value, allow_empty=False):
    return (
        isinstance(value, list)
        and (allow_empty or len(value) > 0)
        and all(isinstance(v, str) for v in value)
        and len(set(value)) == len(value)
    )


def _text_problem(value, limit):
    """Return a reason if `value` is not a single-line printable text, else None."""
    if not isinstance(value, str):
        return "is not text"
    if value == "" or value != value.strip():
        return "is empty or has leading/trailing whitespace"
    if len(value) > limit:
        return f"is longer than {limit} characters"
    if not value.isprintable():
        return "contains control, newline or non-printable characters"
    return None


def _branch_problem(value):
    """Reuse scripts/check-branch-name.py (pure string check). Fails closed if it cannot load."""
    if not isinstance(value, str):
        return "is not text"
    global _BRANCH_MODULE
    try:
        if _BRANCH_MODULE is None:
            spec = importlib.util.spec_from_file_location(
                "kan20_check_branch_name", BRANCH_VALIDATOR_PATH
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            _BRANCH_MODULE = module
        return _BRANCH_MODULE.validate(value)
    except (
        Exception  # noqa: BLE001 - fail-closed boundary: any failure becomes a denial/fallback and never propagates
    ):  # fail closed: any problem loading the branch validator is a denial
        return "branch-name validator could not be loaded"


def _host_problem(host):
    """A host must be a registered-style domain name: no IP literal in any notation, no bare name."""
    labels = host.split(".")
    if len(labels) < 2 or any(_DOMAIN_LABEL.fullmatch(part) is None for part in labels):
        return "host is not a domain name (IP addresses, bare names and malformed hosts are refused)"
    if _TLD.fullmatch(labels[-1]) is None:
        return "host is not a domain name (a numeric or IP-style last label is refused)"
    return None


def _url_problem(value, hosts=()):
    """Return a reason if `value` is not an acceptable evidence URL, else None.

    https only; no userinfo (user:pass@host); no IP literal (dotted, decimal, hex, octal or [v6]);
    a plain domain name host; and, only if `hosts` is non-empty (optional allowlist, default off),
    the host must be one of `hosts`.
    """
    if not isinstance(value, str) or len(value) > MAX_URL:
        return "is not a plain https URL"
    if not value.startswith("https://"):
        return "is not a plain https URL (only https is accepted)"
    authority = re.split(r"[/?#]", value[len("https://") :], maxsplit=1)[0]
    if "@" in authority:
        return (
            "is not accepted: a URL with user information (user:pass@host) is refused"
        )
    if _URL.fullmatch(value) is None:
        return "is not a plain https URL"
    host = authority.split(":", 1)[0]
    why = _host_problem(host)
    if why:
        return "is not accepted: " + why
    if hosts and host.lower() not in hosts:
        return "is not accepted: host is not in the configured evidence_url_hosts allowlist"
    return None


def _field_problem(kind, value, hosts=()):
    if kind == "text":
        return _text_problem(value, MAX_TEXT)
    if kind == "url":
        return _url_problem(value, hosts)
    if kind == "branch":
        return _branch_problem(value)
    if kind == "true":
        return None if value is True else "must be the boolean true"
    if kind == "bool":
        return None if isinstance(value, bool) else "must be a boolean"
    return "has an unknown evidence type"


def _real_label_names(data):
    names = set()
    for key, entry in data["labels"].items():
        if "label_name" in entry:
            if isinstance(entry["label_name"], str):
                names.add(entry["label_name"])
        else:
            names.add(key)
    return names


def _kind(data, actor):
    return data["actor_types"][actor]["kind"]


# ---------------------------------------------------------------------------------------------
# allowlist schema validation
# ---------------------------------------------------------------------------------------------


def _done_guard_errors(data):
    """No non-human actor may reach, leave or assert a human-only status such as Done."""
    errors = []
    human_only = set(data["human_only_statuses"])
    non_human = [a for a, v in data["actor_types"].items() if v["kind"] != "human"]
    for t in data["transitions"]:
        if human_only & set(t["to"]) or human_only & set(t["from"]):
            for actor in t["actors"]:
                if (
                    actor not in data["actor_types"]
                    or data["actor_types"][actor]["kind"] != "human"
                ):
                    errors.append(
                        f"transition {t['id']}: non-human actor {actor!r} touches a human-only status"
                    )
    # reachability: every status a non-human actor can move an issue to, from any status
    for actor in non_human:
        reachable_targets = {
            to for t in data["transitions"] if actor in t["actors"] for to in t["to"]
        }
        if human_only & reachable_targets:
            errors.append(f"actor {actor!r} can reach a human-only status")
    return errors


def _done_source_errors(data):
    """Done is reachable only from In Review, only by a human, and never while exec-rework is present."""
    errors = []
    for t in data["transitions"]:
        if "Done" in t["to"]:
            if t["from"] != ["In Review"]:
                errors.append(
                    f"transition {t['id']}: Done may only be reached from In Review"
                )
            if t["to"] != ["Done"]:
                errors.append(
                    f"transition {t['id']}: a transition to Done must not have other targets"
                )
            if "exec-rework" not in t.get("when_labels_before_exclude", []):
                errors.append(
                    f"transition {t['id']}: Done must be denied while exec-rework is present"
                )
    if not any("Done" in t["to"] for t in data["transitions"]):
        errors.append("the allowlist must contain the human accept_done transition")
    return errors


def _lifecycle_errors(data):
    """The rework lifecycle is documentation that must agree with the transitions."""
    errors = []
    life = data["rework_lifecycle"]
    if (
        not isinstance(life, dict)
        or set(life) != {"steps", "never"}
        or not isinstance(life["steps"], list)
        or not life["steps"]
        or not _is_str_list(life["never"])
    ):
        return ["rework_lifecycle must be {steps, never}"]
    by_id = {t["id"]: t for t in data["transitions"]}
    states = []
    for step in life["steps"]:
        if (
            not isinstance(step, dict)
            or not {"state", "jira_status", "note"} <= set(step)
            or not set(step) <= {"state", "jira_status", "note", "transition"}
            or not all(isinstance(step[k], str) for k in step)
            or step["jira_status"] not in data["statuses"]
        ):
            return ["rework_lifecycle has a malformed step"]
        states.append(step["state"])
        tid = step.get("transition")
        if tid is not None and (
            tid not in by_id or step["jira_status"] not in by_id[tid]["to"]
        ):
            errors.append(
                f"rework_lifecycle step {step['state']!r}: transition {tid!r} does not lead to {step['jira_status']!r}"
            )
    expected = ["REWORK REQUIRED", "REWORK", "FIX", "RE-REVIEW", "ACCEPTED"]
    if states != expected:
        errors.append(f"rework_lifecycle states must be {expected}")
        return errors
    statuses = [s["jira_status"] for s in life["steps"]]
    if statuses != ["In Review", "In Progress", "In Progress", "In Review", "Done"]:
        errors.append(
            "rework_lifecycle must go In Review, In Progress, In Progress, In Review, Done"
        )
    if [s.get("transition") for s in life["steps"]] != [
        None,
        "send_to_rework",
        None,
        "complete_rework",
        "accept_done",
    ]:
        errors.append(
            "rework_lifecycle must use send_to_rework, complete_rework and accept_done"
        )
    return errors


def _comment_fields_wellformed(fields):
    if not isinstance(fields, list) or not fields:
        return False
    names = []
    for f in fields:
        if (
            not isinstance(f, dict)
            or set(f) != {"name", "type"}
            or not isinstance(f["name"], str)
            or _COMMENT_KEY.fullmatch(f["name"]) is None
            or f["name"] != " ".join(f["name"].split())
            or f["type"] not in _COMMENT_FIELD_TYPES
        ):
            return False
        names.append(f["name"])
    return len(set(names)) == len(names)


def validate_allowlist(data):
    """Return a list of error strings (empty list = the allowlist is well formed and safe)."""
    errors = []
    if not isinstance(data, dict):
        return ["allowlist is not a JSON object"]
    if not (_TOP_KEYS - _TOP_KEYS_OPTIONAL) <= set(data) or not set(data) <= _TOP_KEYS:
        missing = sorted((_TOP_KEYS - _TOP_KEYS_OPTIONAL) - set(data))
        extra = sorted(set(data) - _TOP_KEYS)
        return [f"top-level keys wrong: missing {missing}, unexpected {extra}"]
    if data["schema_version"] != 1 or isinstance(data["schema_version"], bool):
        errors.append("schema_version must be 1")
    for key in ("title", "approval"):
        if not isinstance(data[key], str) or not data[key].strip():
            errors.append(f"{key} must be non-empty text")
    if not _is_str_list(data["sources"]):
        errors.append("sources must be a non-empty list of unique strings")

    # statuses: exactly the existing Jira workflow
    if data["statuses"] != ["To Do", "In Progress", "In Review", "Done"]:
        errors.append(
            "statuses must be exactly ['To Do', 'In Progress', 'In Review', 'Done'] (existing Jira workflow only)"
        )
    if data["human_only_statuses"] != ["Done"]:
        errors.append("human_only_statuses must be exactly ['Done']")
    if errors:
        return errors  # later checks index into these structures

    # actor types
    actors = data["actor_types"]
    if not isinstance(actors, dict) or not actors:
        return errors + ["actor_types must be a non-empty object"]
    for name, spec in actors.items():
        if not isinstance(name, str) or not _NAME.fullmatch(name):
            errors.append(f"actor type name {name!r} is invalid")
        if (
            not isinstance(spec, dict)
            or set(spec) != {"kind", "description"}
            or spec.get("kind") not in _ACTOR_KINDS
            or not isinstance(spec.get("description"), str)
        ):
            errors.append(
                f"actor type {name!r} must be {{kind, description}} with kind in {_ACTOR_KINDS}"
            )
    if errors:
        return errors
    if HUMAN_ACTOR not in actors or actors[HUMAN_ACTOR]["kind"] != "human":
        errors.append("actor type 'human' with kind 'human' is required")
    if [n for n, s in actors.items() if s["kind"] == "human"] != [HUMAN_ACTOR]:
        errors.append("'human' must be the only actor type of kind 'human'")
    if not any(s["kind"] == "agent" for s in actors.values()):
        errors.append("at least one actor type of kind 'agent' is required")
    if not any(s["kind"] == "automation" for s in actors.values()):
        errors.append("an actor type of kind 'automation' is required")

    # optional evidence URL host allowlist (default off: absent or empty list)
    hosts = data.get("evidence_url_hosts", [])
    if (
        not isinstance(hosts, list)
        or not all(
            isinstance(h, str) and h == h.lower() and _host_problem(h) is None
            for h in hosts
        )
        or len(set(hosts)) != len(hosts)
    ):
        errors.append(
            "evidence_url_hosts must be a list of unique lowercase domain names (empty = off)"
        )

    # evidence fields
    fields = data["evidence_fields"]
    if not isinstance(fields, dict) or not fields:
        return errors + ["evidence_fields must be a non-empty object"]
    for name, kind in fields.items():
        if (
            not isinstance(name, str)
            or not _FIELD.fullmatch(name)
            or kind not in _EVIDENCE_TYPES
        ):
            errors.append(
                f"evidence field {name!r} must map to one of {_EVIDENCE_TYPES}"
            )

    # labels
    labels = data["labels"]
    if not isinstance(labels, dict) or "exec-rework" not in labels:
        return errors + ["labels must be an object containing 'exec-rework'"]
    for key, entry in labels.items():
        if (
            not isinstance(entry, dict)
            or not {"approval", "meaning"} <= set(entry)
            or not set(entry)
            <= {"approval", "meaning", "allowed_only_in_status", "label_name"}
        ):
            errors.append(f"label entry {key!r} has wrong keys")
            continue
        if (
            "label_name" in entry
            and entry["label_name"] is not None
            and (
                not isinstance(entry["label_name"], str)
                or not _LABEL.fullmatch(entry["label_name"])
            )
        ):
            errors.append(
                f"label entry {key!r}: label_name must be null or a valid label"
            )
        if (
            "allowed_only_in_status" in entry
            and entry["allowed_only_in_status"] not in data["statuses"]
        ):
            errors.append(
                f"label entry {key!r}: allowed_only_in_status is not a known status"
            )
    if errors:
        return errors
    if labels["exec-rework"].get("allowed_only_in_status") != "In Progress":
        errors.append("exec-rework must be allowed only in status 'In Progress'")
    real_labels = _real_label_names(data)
    words = data["assertion_label_words"]
    if not _is_str_list(words) or any(w != w.lower() or not w.isalpha() for w in words):
        errors.append(
            "assertion_label_words must be a non-empty list of lowercase words"
        )

    # assertion markers (approval / acceptance / release statements)
    markers = data["assertion_markers"]
    if not isinstance(markers, dict) or not {"APPROVED", "DONE", "RELEASED"} <= set(
        markers
    ):
        return errors + ["assertion_markers must cover APPROVED, DONE and RELEASED"]
    for marker, spec in markers.items():
        if not isinstance(marker, str) or not re.fullmatch(r"[A-Z]{3,20}", marker):
            errors.append(f"assertion marker {marker!r} must be 3-20 capital letters")
            continue
        if (
            not isinstance(spec, dict)
            or set(spec)
            != {"actors", "requires_evidence", "distinct_actor_and_owner_for_agents"}
            or not _is_str_list(spec["actors"])
            or not _is_str_list(spec["requires_evidence"], True)
            or not isinstance(spec["distinct_actor_and_owner_for_agents"], bool)
        ):
            errors.append(f"assertion marker {marker!r} has wrong shape")
            continue
        for a in spec["actors"]:
            if a not in actors:
                errors.append(f"assertion marker {marker!r}: unknown actor {a!r}")
        for f in spec["requires_evidence"]:
            if f not in fields:
                errors.append(
                    f"assertion marker {marker!r}: unknown evidence field {f!r}"
                )
        if errors:
            continue
        if marker != "APPROVED" and spec["actors"] != [HUMAN_ACTOR]:
            errors.append(f"assertion marker {marker!r} may only be written by 'human'")
        if marker == "APPROVED" and any(
            actors[a]["kind"] == "automation" for a in spec["actors"]
        ):
            errors.append("automation may not write APPROVED")
        if marker == "APPROVED" and "owner_agent" in spec["actors"]:
            errors.append("owner_agent may not write APPROVED (self-approval)")
    if errors:
        return errors

    def check_comment_requirement(owner, cr):
        if cr is None:
            return
        if (
            not isinstance(cr, dict)
            or set(cr) != {"marker", "required_fields"}
            or not isinstance(cr["marker"], str)
            or not re.fullmatch(r"[A-Z]{3,20}", cr["marker"])
            or not _comment_fields_wellformed(cr["required_fields"])
        ):
            errors.append(
                f"{owner}: comment_requirement must be {{marker, required_fields: [{{name, type}}]}} "
                f"with types in {_COMMENT_FIELD_TYPES}"
            )
        elif cr["marker"] in markers:
            errors.append(
                f"{owner}: comment marker {cr['marker']!r} collides with an assertion marker"
            )

    # transitions
    transitions = data["transitions"]
    if not isinstance(transitions, list) or not transitions:
        return errors + ["transitions must be a non-empty list"]
    seen_ids = set()
    for t in transitions:
        if (
            not isinstance(t, dict)
            or not _TRANSITION_REQUIRED <= set(t)
            or not set(t) <= _TRANSITION_KEYS
        ):
            errors.append("a transition has missing or unexpected keys")
            continue
        tid = t["id"]
        if not isinstance(tid, str) or not _NAME.fullmatch(tid) or tid in seen_ids:
            errors.append(f"transition id {tid!r} is invalid or duplicated")
            continue
        seen_ids.add(tid)
        if (
            not _is_str_list(t["from"])
            or not _is_str_list(t["to"])
            or not set(t["from"]) <= set(data["statuses"])
            or not set(t["to"]) <= set(data["statuses"])
        ):
            errors.append(
                f"transition {tid}: from/to must be non-empty lists of known statuses"
            )
            continue
        if set(t["from"]) & set(t["to"]):
            errors.append(f"transition {tid}: from and to overlap")
        if not _is_str_list(t["actors"]) or not set(t["actors"]) <= set(actors):
            errors.append(
                f"transition {tid}: actors must be a non-empty list of known actor types"
            )
            continue
        if not isinstance(t["approval"], str) or not t["approval"].strip():
            errors.append(f"transition {tid}: approval note is required")
        if not _is_str_list(t["proposed_assumptions"], True):
            errors.append(
                f"transition {tid}: proposed_assumptions must be a list of strings"
            )
        for key in (
            "when_labels_before_include",
            "when_labels_before_exclude",
            "labels_after_include",
            "labels_after_exclude",
        ):
            if key in t and (
                not _is_str_list(t[key]) or not set(t[key]) <= real_labels
            ):
                errors.append(f"transition {tid}: {key} must be a list of known labels")
        check_comment_requirement(f"transition {tid}", t.get("comment_requirement"))
        conds = t.get("conditional_comment_requirements", [])
        if not isinstance(conds, list) or any(
            not isinstance(c, dict)
            or set(c) != {"when_labels_after_include", "comment_requirement"}
            or not _is_str_list(c["when_labels_after_include"])
            or not set(c["when_labels_after_include"]) <= real_labels
            or c["comment_requirement"] is None
            for c in conds
        ):
            errors.append(
                f"transition {tid}: conditional_comment_requirements is malformed"
            )
        else:
            for c in conds:
                check_comment_requirement(
                    f"transition {tid} (conditional)", c["comment_requirement"]
                )
        if (
            "Done" in t["from"]
            and "In Progress" in t["to"]
            and not any(
                REWORK_LABEL in c.get("when_labels_after_include", [])
                for c in (conds if isinstance(conds, list) else [])
                if isinstance(c, dict)
            )
        ):
            errors.append(
                f"transition {tid}: reopening to In Progress must require a REWORK comment when exec-rework is present"
            )
        reqs = t["evidence_requirements"]
        if not isinstance(reqs, list) or not reqs:
            errors.append(
                f"transition {tid}: at least one evidence requirement is mandatory"
            )
            continue
        for r in reqs:
            if (
                not isinstance(r, dict)
                or not {"description", "any_of"} <= set(r)
                or not set(r) <= {"description", "any_of", "only_if_field_true"}
                or not isinstance(r["description"], str)
                or not _is_str_list(r["any_of"])
                or not set(r["any_of"]) <= set(fields)
            ):
                errors.append(f"transition {tid}: malformed evidence requirement")
                continue
            cond = r.get("only_if_field_true")
            if cond is not None and fields.get(cond) != "bool":
                errors.append(
                    f"transition {tid}: only_if_field_true must name a 'bool' evidence field"
                )
        if (
            t["to"] == ["In Progress"]
            and t["from"] == ["In Review"]
            and "exec-rework" not in t.get("labels_after_include", [])
        ):
            errors.append(
                f"transition {tid}: In Review -> In Progress must add exec-rework (rework = In Progress + label + comment)"
            )
        if (
            t["to"] == ["In Progress"]
            and t["from"] == ["In Review"]
            and "comment_requirement" not in t
        ):
            errors.append(f"transition {tid}: rework must require an explicit comment")
    if errors:
        return errors

    # status-unchanged events
    events = data["status_unchanged_events"]
    if not isinstance(events, list):
        return errors + ["status_unchanged_events must be a list"]
    for ev in events:
        if not isinstance(ev, dict) or set(ev) != _EVENT_KEYS:
            errors.append("a status_unchanged_event has wrong keys")
            continue
        if (
            not _is_str_list(ev["statuses"])
            or not set(ev["statuses"]) <= set(data["statuses"])
            or set(ev["statuses"]) & set(data["human_only_statuses"])
        ):
            errors.append(
                f"event {ev.get('id')!r}: statuses must be known non-human-only statuses"
            )
        if not _is_str_list(ev["actors"]) or not set(ev["actors"]) <= set(actors):
            errors.append(f"event {ev.get('id')!r}: unknown actors")
        elif (
            any(actors[a]["kind"] == "automation" for a in ev["actors"])
            and ev["id"] != "blocked"
        ):
            errors.append(f"event {ev['id']!r}: automation not allowed")
        if ev["comment_requirement"] is None:
            errors.append(f"event {ev.get('id')!r}: a comment is required")
        else:
            check_comment_requirement(
                f"event {ev.get('id')!r}", ev["comment_requirement"]
            )
    if errors:
        return errors

    # the central rule: no agent / automation path to Done (or any human-only status)
    errors.extend(_done_guard_errors(data))
    errors.extend(_done_source_errors(data))
    errors.extend(_lifecycle_errors(data))
    return errors


def load_allowlist(path=DEFAULT_ALLOWLIST_PATH):
    """Read the allowlist JSON from a local file (no network). Raises ValueError if unreadable."""
    try:
        if os.path.getsize(path) > MAX_FILE_BYTES:
            raise ValueError("allowlist file is too large")
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError) as exc:
        raise ValueError(f"cannot read allowlist: {type(exc).__name__}") from None


# ---------------------------------------------------------------------------------------------
# the decision function
# ---------------------------------------------------------------------------------------------


def _deny(reasons, transition_id=None):
    return Decision(False, transition_id, tuple(reasons))


def _fold_label(label):
    """Canonical form used for every label comparison (P5-4): case-folded, with the separators
    '_', '.' and ':' treated as '-', so 'Exec-Rework', 'EXEC_REWORK' and 'exec.rework' are all
    'exec-rework'. Input is already limited to ASCII by _LABEL, so look-alike Unicode, spaces and
    control characters never get this far: they make the whole request malformed (denied)."""
    return re.sub(r"[_.:]", "-", label.casefold())


def _normalise_labels(name, value, problems):
    if isinstance(value, (str, bytes)) or not isinstance(
        value, (list, tuple, set, frozenset)
    ):
        problems.append(f"{name} must be a list of labels")
        return None
    if len(value) > MAX_LABELS:
        problems.append(f"{name} has more than {MAX_LABELS} labels")
        return None
    out = set()
    for item in value:
        if not isinstance(item, str) or _LABEL.fullmatch(item) is None:
            problems.append(f"{name} contains a malformed label")
            return None
        out.add(_fold_label(item))
    return out


def _marker_regex(markers):
    return re.compile(
        r"(?:^|[;\s])(" + "|".join(sorted(markers)) + r")\s*:", re.IGNORECASE
    )


def _parse_comment_fields(rest):
    """Parse the text after 'MARKER:' into {key: [values]}. Fields are separated by ';' and each is
    'key: value' (split at the FIRST colon, so URLs keep theirs). A segment with no colon is free
    text and is ignored. Keys are lowercase with single spaces."""
    fields = {}
    for segment in rest.split(";"):
        if ":" not in segment:
            continue
        key, value = segment.split(":", 1)
        fields.setdefault(" ".join(key.lower().split()), []).append(value.strip())
    return fields


def _comment_value_problem(kind, value, hosts):
    if value == "":
        return "is empty"
    if kind == "url":
        return _url_problem(value, hosts)
    if len(value) > MAX_FIELD_VALUE:
        return f"is longer than {MAX_FIELD_VALUE} characters"
    if re.search(r"[A-Za-z0-9]", value) is None:
        return "has no letters or digits"
    if value.startswith("<") and value.endswith(">"):
        return "is an unfilled template placeholder"
    if kind == "actor" and _ACTOR_ID.fullmatch(value) is None:
        return "is not a valid name or id"
    return None


def _comment_requirement_problems(comment, req, hosts=()):
    """The comment must start with 'MARKER:' and carry every required `key: value` field with a
    non-empty, well-formed value (P5-1). Substring presence of 'by:' etc. is not enough."""
    if comment is None:
        return [f"a comment starting with '{req['marker']}:' is required"]
    prefix = req["marker"] + ":"
    if not comment.startswith(prefix) or not comment[len(prefix) :].strip():
        return [f"comment must start with '{prefix}' followed by text"]
    fields = _parse_comment_fields(comment[len(prefix) :])
    reasons = []
    for spec in req["required_fields"]:
        name = spec["name"]
        values = fields.get(name)
        if not values:
            reasons.append(f"comment lacks the field '{name}:'")
        elif len(values) > 1:
            reasons.append(f"comment field '{name}:' appears more than once")
        else:
            why = _comment_value_problem(spec["type"], values[0], hosts)
            if why:
                reasons.append(f"comment field '{name}:' {why}")
    return reasons


def _rework_label_change_problems(transition_id, before, after):
    """exec-rework may only be added or removed by send_to_rework, complete_rework, return_to_todo
    and reopen (P5-2). In particular a BLOCKED note (status unchanged) must not add or remove it,
    or it would be a back door around the rework-complete evidence."""
    if (REWORK_LABEL in before) == (
        REWORK_LABEL in after
    ) or transition_id in REWORK_LABEL_TRANSITIONS:
        return []
    verb = "add" if REWORK_LABEL in after else "remove"
    return [
        (
            f"{transition_id} may not {verb} the label {REWORK_LABEL!r} (only send_to_rework, "
            f"complete_rework, return_to_todo and reopen change it)"
        )
    ]


def _conditional_comment_problems(rule, after, comment, hosts=()):
    """Extra comment requirements that apply because of labels present after the change (P5-3):
    for example a reopen that leaves exec-rework on the issue needs a valid REWORK comment."""
    reasons = []
    for cond in rule.get("conditional_comment_requirements", []):
        if {_fold_label(x) for x in cond["when_labels_after_include"]} <= after:
            reasons += _comment_requirement_problems(
                comment, cond["comment_requirement"], hosts
            )
    return reasons


def _evaluate(
    data,
    from_status,
    to_status,
    actor_type,
    labels_before,
    labels_after,
    evidence=None,
    comment=None,
    actor_id=None,
    owner_id=None,
):
    """Decide against an allowlist that is ALREADY known to be valid (see check_transition)."""
    problems = []
    # ---- shape of every input ----
    for name, value, pattern in (
        ("from_status", from_status, _STATUS),
        ("to_status", to_status, _STATUS),
        ("actor_type", actor_type, _NAME),
    ):
        if not isinstance(value, str) or pattern.fullmatch(value) is None:
            problems.append(f"{name} is malformed")
    before = _normalise_labels("labels_before", labels_before, problems)
    after = _normalise_labels("labels_after", labels_after, problems)
    if evidence is None:
        evidence = {}
    if not isinstance(evidence, dict):
        problems.append("evidence must be an object")
        evidence = {}
    if comment is not None and _text_problem(comment, MAX_COMMENT):
        problems.append(f"comment {_text_problem(comment, MAX_COMMENT)}")
    for name, value in (("actor_id", actor_id), ("owner_id", owner_id)):
        if value is not None and (
            not isinstance(value, str) or _ACTOR_ID.fullmatch(value) is None
        ):
            problems.append(f"{name} is malformed")
    if problems:
        return _deny(problems)

    # ---- known vocabulary ----
    if from_status not in data["statuses"]:
        problems.append(f"unknown from_status {from_status!r}")
    if to_status not in data["statuses"]:
        problems.append(f"unknown to_status {to_status!r}")
    if actor_type not in data["actor_types"]:
        problems.append(f"unknown actor_type {actor_type!r}")
    if problems:
        return _deny(problems)

    # ---- the Done guard: hard-coded, independent of the data file ----
    if to_status in HUMAN_ONLY_STATUSES and actor_type != HUMAN_ACTOR:
        return _deny(
            [f"{actor_type} may never move an issue to {to_status}; only a human may"]
        )
    if from_status in HUMAN_ONLY_STATUSES and actor_type != HUMAN_ACTOR:
        return _deny(
            [
                f"{actor_type} may never reopen or change an issue in {from_status}; only a human may"
            ]
        )

    # ---- evidence field types (every supplied field must be known and well formed) ----
    hosts = tuple(data.get("evidence_url_hosts", []))
    for key, value in evidence.items():
        kind = data["evidence_fields"].get(key) if isinstance(key, str) else None
        if kind is None:
            problems.append("unknown evidence field " + ascii(key))
            continue
        why = _field_problem(kind, value, hosts)
        if why:
            problems.append(f"evidence field {key} {why}")
    if problems:
        return _deny(problems)

    # ---- find the rule ----
    if from_status == to_status:
        return _evaluate_unchanged(
            data,
            from_status,
            actor_type,
            before,
            after,
            evidence,
            comment,
            actor_id,
            owner_id,
            hosts,
        )
    chosen = None
    candidates = [
        t
        for t in data["transitions"]
        if from_status in t["from"] and to_status in t["to"]
    ]
    if not candidates:
        return _deny(
            [f"transition {from_status!r} -> {to_status!r} is not in the allowlist"]
        )
    for t in candidates:
        if {
            _fold_label(x) for x in t.get("when_labels_before_include", [])
        } <= before and not (
            {_fold_label(x) for x in t.get("when_labels_before_exclude", [])} & before
        ):
            chosen = t
            break
    if chosen is None:
        return _deny(
            [
                (
                    f"transition {from_status!r} -> {to_status!r} is not allowed with the current labels "
                    f"(for example the rework-complete path needs exec-rework present, the normal path needs it absent)"
                )
            ]
        )
    tid = chosen["id"]
    if actor_type not in chosen["actors"]:
        return _deny(
            [
                f"actor {actor_type!r} may not perform {from_status!r} -> {to_status!r} ({tid})"
            ],
            tid,
        )

    reasons = []
    reasons += _label_problems(data, chosen, to_status, before, after, actor_type)
    reasons += _rework_label_change_problems(tid, before, after)
    reasons += _evidence_problems(data, chosen["evidence_requirements"], evidence)
    if "comment_requirement" in chosen:
        reasons += _comment_requirement_problems(
            comment, chosen["comment_requirement"], hosts
        )
    reasons += _conditional_comment_problems(chosen, after, comment, hosts)
    reasons += _assertion_problems(
        data, actor_type, comment, evidence, actor_id, owner_id
    )
    return Decision(not reasons, tid, tuple(reasons))


def _evaluate_unchanged(
    data,
    status,
    actor_type,
    before,
    after,
    evidence,
    comment,
    actor_id,
    owner_id,
    hosts=(),
):
    events = [e for e in data["status_unchanged_events"] if status in e["statuses"]]
    if not events:
        return _deny([f"no status-unchanged event is allowed in {status!r}"])
    ev = events[0]
    if actor_type not in ev["actors"]:
        return _deny(
            [f"actor {actor_type!r} may not record {ev['id']} in {status!r}"], ev["id"]
        )
    reasons = _comment_requirement_problems(comment, ev["comment_requirement"], hosts)
    reasons += _label_problems(data, {}, status, before, after, actor_type)
    reasons += _rework_label_change_problems(ev["id"], before, after)
    reasons += _assertion_problems(
        data, actor_type, comment, evidence, actor_id, owner_id
    )
    return Decision(not reasons, ev["id"], tuple(reasons))


def _label_problems(data, rule, to_status, before, after, actor_type):
    reasons = []
    for label in rule.get("labels_after_include", []):
        if _fold_label(label) not in after:
            reasons.append(f"label {label!r} must be present after this transition")
    for label in rule.get("labels_after_exclude", []):
        if _fold_label(label) in after:
            reasons.append(f"label {label!r} must be removed by this transition")
    for key, entry in data["labels"].items():
        only = entry.get("allowed_only_in_status")
        name = entry.get("label_name", key)
        if only is not None and _fold_label(name) in after and to_status != only:
            reasons.append(f"label {name!r} may only be present in status {only!r}")
    # automation and agents may not add labels that assert approval, acceptance or release
    if actor_type != HUMAN_ACTOR:
        for label in sorted(after - before):
            tokens = set(re.split(r"[-_.:]+", label.lower()))
            if tokens & set(data["assertion_label_words"]):
                reasons.append(
                    f"{actor_type} may not add label {label!r} (asserts approval, acceptance or release)"
                )
    return reasons


def _evidence_problems(data, requirements, evidence):
    reasons = []
    for req in requirements:
        cond = req.get("only_if_field_true")
        if cond is not None and evidence.get(cond) is not True:
            continue
        if not any(f in evidence for f in req["any_of"]):
            reasons.append(
                f"missing evidence: {req['description']} (need one of: {', '.join(req['any_of'])})"
            )
    return reasons


def _assertion_problems(data, actor_type, comment, evidence, actor_id, owner_id):
    """Approval / acceptance / release statements are written by the approving human (or a reviewer
    gate agent for APPROVED), never by automation or by the owner of the work. Heuristic on free text."""
    if comment is None:
        return []
    reasons = []
    found = {
        m.upper() for m in _marker_regex(data["assertion_markers"]).findall(comment)
    }
    for marker in sorted(found):
        spec = data["assertion_markers"][marker]
        if actor_type not in spec["actors"]:
            reasons.append(f"{actor_type} may not write a '{marker}:' statement")
            continue
        for f in spec["requires_evidence"]:
            if f not in evidence:
                reasons.append(f"'{marker}:' statement needs evidence field {f}")
        if (
            spec["distinct_actor_and_owner_for_agents"]
            and _kind(data, actor_type) != "human"
        ):
            if actor_id is None or owner_id is None:
                reasons.append(
                    f"'{marker}:' statement by an agent needs actor_id and owner_id (self-approval check)"
                )
            elif actor_id.lower() == owner_id.lower():
                reasons.append(
                    f"self-approval: the author of the work may not write '{marker}:'"
                )
    return reasons


def check_transition(
    from_status,
    to_status,
    actor_type,
    labels_before,
    labels_after,
    evidence=None,
    comment=None,
    actor_id=None,
    owner_id=None,
    allowlist=None,
):
    """Return Decision(allowed, transition_id, reasons). Never raises on bad input; fails closed.

    from_status/to_status: one of 'To Do', 'In Progress', 'In Review', 'Done' (equal values mean a
        status-unchanged note such as BLOCKED).
    actor_type: 'human', 'owner_agent', 'reviewer_agent' or 'automation'.
    labels_before / labels_after: the issue's labels before and after the change (lists of strings).
    evidence: object of known evidence fields (see the allowlist file).
    comment: the single-line Jira comment that goes with the change, if any.
    actor_id / owner_id: identities, needed only for the agent self-approval check on APPROVED.
    allowlist: parsed allowlist object; the default file is loaded and validated when omitted.
    """
    try:
        data = load_allowlist() if allowlist is None else allowlist
    except ValueError as exc:
        return _deny([str(exc)])
    schema_errors = validate_allowlist(data)
    if schema_errors:
        return _deny(["allowlist is invalid: " + "; ".join(schema_errors[:5])])
    try:
        return _evaluate(
            data,
            from_status,
            to_status,
            actor_type,
            labels_before,
            labels_after,
            evidence,
            comment,
            actor_id,
            owner_id,
        )
    except Exception:  # noqa: BLE001 - fail closed: an unexpected failure is never an "allow"
        return _deny(["internal error while checking the request"])


# ---------------------------------------------------------------------------------------------
# command line
# ---------------------------------------------------------------------------------------------


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Check a KAN Jira transition against the allowlist (pure logic)."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--validate-allowlist",
        action="store_true",
        help="validate the allowlist data file itself",
    )
    group.add_argument(
        "--request",
        metavar="FILE",
        help="JSON file with one request (keys = check_transition arguments)",
    )
    parser.add_argument(
        "--allowlist",
        default=DEFAULT_ALLOWLIST_PATH,
        help="allowlist file (default: bundled)",
    )
    args = parser.parse_args(argv)

    try:
        data = load_allowlist(args.allowlist)
    except ValueError as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 1
    errors = validate_allowlist(data)
    if args.validate_allowlist:
        if errors:
            for e in errors:
                print(f"INVALID: {e}", file=sys.stderr)
            return 1
        print(
            f"OK: allowlist is valid ({len(data['transitions'])} transitions, no agent or automation path to Done)"
        )
        return 0

    try:
        if os.path.getsize(args.request) > MAX_FILE_BYTES:
            raise ValueError("request file is too large")
        with open(args.request, encoding="utf-8") as fh:
            request = json.load(fh)
        if not isinstance(request, dict):
            raise ValueError("request is not an object")  # noqa: TRY004 - ValueError on purpose: the caller fail-closes on ValueError; TypeError would escape it
        allowed_keys = {
            "from_status",
            "to_status",
            "actor_type",
            "labels_before",
            "labels_after",
            "evidence",
            "comment",
            "actor_id",
            "owner_id",
        }
        if not set(request) <= allowed_keys or not {
            "from_status",
            "to_status",
            "actor_type",
            "labels_before",
            "labels_after",
        } <= set(request):
            raise ValueError("request has missing or unexpected keys")
    except (OSError, ValueError) as exc:
        print(f"error: unusable request file: {type(exc).__name__}", file=sys.stderr)
        return 2
    decision = check_transition(allowlist=data, **request)
    if decision.allowed:
        print(f"ALLOW: {decision.transition_id}")
        return 0
    for reason in decision.reasons:
        print("DENY: " + ascii(reason)[1:-1], file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
