#!/usr/bin/env python3
"""Check that a pull request is linked to its Jira issue (KAN-20, "PR links"). Pure logic, fail closed.

Inputs are the PR title, the PR body and the PR head branch. ALL THREE ARE HOSTILE DATA: they are
only compared with fixed patterns, never evaluated, never passed to a shell or a process, never
used as an option or a path, and they are printed back only as fixed messages (the branch name,
when it is invalid, is echoed escaped and length-bounded).

Rules (see docs/pr-jira-link-check.md for the CLI contract):
  1. The branch must pass scripts/check-branch-name.py (the same validator, loaded from its file).
     Its Jira key KAN-<n> is "the branch key".
  2. The branch key must appear as a KAN-<n> reference in the PR title or the PR body
     (upper case, whole token: "KAN-20" does not match "KAN-200", "KAN-2", "kan-20" or "KAN-020").
  3. The PR body must contain the branch key, either bare or inside a Jira URL.
     A Jira URL is https://liferescue.atlassian.net/... with that exact host (case-insensitive),
     no user information, no port other than 443, and the key in its path or query.
  4. Look-alike Jira hosts are refused wherever they appear in title or body: any other host
     containing "liferescue" or "atlassian.net", a Jira-host name inside another URL's path,
     query or fragment, a Jira URL over http, user information (user:pass@host), and internationalised
     (non-ASCII or xn--) hosts.
  5. PROPOSED ASSUMPTION - REQUIRES HUMAN APPROVAL: the live backlog issues KAN-1, KAN-2, KAN-3 and
     SAM1 (project) are protected ("must not be touched", KAN-20 plan N1). A branch whose key is
     KAN-1..KAN-3, or a Jira URL in the PR text that points at KAN-1..KAN-3 or at a SAM1 issue, is refused.

Command line: no arguments (any argument is a usage error and is never echoed). Input comes from
the environment variables PR_TITLE, PR_BODY and PR_BRANCH, or from a JSON file named by PR_JSON_FILE
(object with exactly the keys "title", "body", "branch"). Not both.
Exit code 0 = linked, 1 = invalid (fixed reason codes on stderr), 2 = usage / unusable input.
A CI step must treat ANY non-zero exit code as failure.

Standard library only; no network access, no calls to other programs.
"""

import importlib.util
import json
import os
import re
import sys
from collections import namedtuple
from typing import List, Mapping, Optional, Sequence, Tuple
from urllib.parse import urlsplit

HERE = os.path.dirname(os.path.abspath(__file__))
BRANCH_VALIDATOR_PATH = os.path.join(HERE, "check-branch-name.py")

JIRA_HOST = "liferescue.atlassian.net"
PROTECTED_KAN_NUMBERS = frozenset({1, 2, 3})  # PROPOSED ASSUMPTION (KAN-20 plan N1)
PROTECTED_PROJECTS = frozenset({"SAM1"})

ENV_TITLE = "PR_TITLE"
ENV_BODY = "PR_BODY"
ENV_BRANCH = "PR_BRANCH"
ENV_FILE = "PR_JSON_FILE"

MAX_TITLE = 500
MAX_BODY = 65536
MAX_BRANCH = 100
MAX_FILE_BYTES = 1048576
ECHO_LIMIT = 80

# Fixed vocabulary of reason codes (the only things the CLI prints besides the key).
CODES = {
    "INPUT_MALFORMED": "an input is missing, not text, too long or contains control characters",
    "BRANCH_INVALID": "the branch name does not follow <type>/KAN-<number>-<description>",
    "BRANCH_VALIDATOR_UNAVAILABLE": "the branch-name validator could not be loaded (fail closed)",
    "PROTECTED_ISSUE": "the branch key is a protected live-backlog issue (KAN-1..KAN-3)",
    "PROTECTED_ISSUE_LINK": "the PR text links a protected issue (KAN-1..KAN-3 or SAM1)",
    "KEY_NOT_IN_TITLE_OR_BODY": "the branch key is not referenced as KAN-<n> in the PR title or body",
    "BODY_LACKS_JIRA_REFERENCE": "the PR body has neither the branch key nor a Jira URL for it",
    "LOOKALIKE_HOST": "a URL or host name imitates the Jira host (or is internationalised)",
    "NON_HTTPS_JIRA_URL": "a Jira URL does not use https",
    "USERINFO_IN_URL": "a URL contains user information (user:pass@host)",
    "JIRA_URL_BAD_FORM": "a Jira URL uses a port or form that is not accepted",
}

Problem = Tuple[str, str]
PrLinkResult = namedtuple("PrLinkResult", ["ok", "key", "problems", "branch_note"])

_KEY_IN_BRANCH = re.compile(r"^[a-z]+/KAN-([1-9][0-9]*)-")
# a KAN-<n> token: not glued to other word characters or hyphens/digits on either side
_KEY_TOKEN = re.compile(r"(?<![A-Za-z0-9_-])KAN-([1-9][0-9]*)(?![A-Za-z0-9_-])")
_PROTECTED_PROJECT_TOKEN = re.compile(r"(?<![A-Za-z0-9_-])(SAM1)-([1-9][0-9]*)(?![A-Za-z0-9_-])")
# The look-behinds make every match start at a token boundary, so long runs of token characters
# cannot cause quadratic backtracking.
_URL_TOKEN = re.compile(r"(?i)(?<![a-z0-9+.-])[a-z][a-z0-9+.-]*://(?:\[[^\s\[\]<>()\"'`]*\])?[^\s<>()\[\]\"'`]*")
_HOSTLIKE = re.compile(r"(?i)(?<![a-z0-9.-])[a-z0-9-]+(?:\.[a-z0-9-]+)+")
_BAD_CONTROL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u202a-\u202e\u2066-\u2069]")
_TRAILING = ".,;:!?*_~"

_BRANCH_MODULE = None


def escaped(text: str) -> str:
    """Printable, single-line, ASCII-only, length-bounded form of untrusted text."""
    if len(text) > ECHO_LIMIT:
        return ascii(text[:ECHO_LIMIT]) + "... [truncated]"
    return ascii(text)


def _branch_problem(branch: str) -> Optional[str]:
    """Run scripts/check-branch-name.py validate(); 'UNAVAILABLE' if it cannot be loaded."""
    global _BRANCH_MODULE
    try:
        if _BRANCH_MODULE is None:
            spec = importlib.util.spec_from_file_location("kan20_check_branch_name", BRANCH_VALIDATOR_PATH)
            module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
            spec.loader.exec_module(module)  # type: ignore[union-attr]
            _BRANCH_MODULE = module
        result = _BRANCH_MODULE.validate(branch)
        return None if result is None else str(result)
    except Exception:  # fail closed: any problem loading the validator is a denial
        return "UNAVAILABLE"


def _text_input_problem(value: object, limit: int, allow_newlines: bool) -> Optional[str]:
    if not isinstance(value, str):
        return "not text"
    if len(value) > limit:
        return "too long"
    if _BAD_CONTROL.search(value):
        return "control characters"
    if not allow_newlines and ("\n" in value or "\r" in value or "\t" in value):
        return "line break in a single-line value"
    return None


def _url_tokens(text: str) -> List[str]:
    tokens = []
    for match in _URL_TOKEN.finditer(text):
        token = match.group(0)
        while token and token[-1] in _TRAILING:
            token = token[:-1]
        tokens.append(token)
    return tokens


def _scan_urls(text: str, branch_key_number: int, problems: List[Problem]) -> List[str]:
    """Check every URL in `text`. Return the list of ACCEPTED Jira URL keys (as 'KAN-<n>' strings)."""
    accepted: List[str] = []
    for token in _url_tokens(text):
        rest = token.split("://", 1)[1]
        rawnet = re.split(r"[/?#]", rest, maxsplit=1)[0]
        tail = rest[len(rawnet) :]
        scheme = token.split("://", 1)[0].lower()
        try:
            urlsplit(token)  # rejects e.g. unbalanced IPv6 brackets
        except ValueError:
            problems.append(("LOOKALIKE_HOST", CODES["LOOKALIKE_HOST"]))
            continue
        if rawnet.startswith("["):  # bracketed (IP-literal style) host
            if "liferescue" in token.lower() or "atlassian.net" in token.lower():
                problems.append(("LOOKALIKE_HOST", CODES["LOOKALIKE_HOST"]))
            continue
        if "@" in rawnet:
            problems.append(("USERINFO_IN_URL", CODES["USERINFO_IN_URL"]))
            continue
        hostport = rawnet
        host, _, port = hostport.partition(":")
        host_l = host.lower()
        if not host_l.isascii() or "xn--" in host_l:
            problems.append(("LOOKALIKE_HOST", CODES["LOOKALIKE_HOST"]))
            continue
        exact = host_l == JIRA_HOST
        mentions_jira_in_tail = JIRA_HOST in tail.lower() or "atlassian.net" in tail.lower()
        if not exact:
            if "liferescue" in host_l or "atlassian.net" in host_l or mentions_jira_in_tail:
                problems.append(("LOOKALIKE_HOST", CODES["LOOKALIKE_HOST"]))
            continue
        # exact Jira host from here on
        if scheme != "https":
            problems.append(("NON_HTTPS_JIRA_URL", CODES["NON_HTTPS_JIRA_URL"]))
            continue
        if port not in ("", "443") or host != host.strip() or hostport.endswith(":"):
            problems.append(("JIRA_URL_BAD_FORM", CODES["JIRA_URL_BAD_FORM"]))
            continue
        for number in _KEY_TOKEN.findall(tail):
            if int(number) in PROTECTED_KAN_NUMBERS:
                problems.append(("PROTECTED_ISSUE_LINK", CODES["PROTECTED_ISSUE_LINK"]))
        if _PROTECTED_PROJECT_TOKEN.search(tail):
            problems.append(("PROTECTED_ISSUE_LINK", CODES["PROTECTED_ISSUE_LINK"]))
        if re.search(r"(?<![A-Za-z0-9_-])KAN-%d(?![A-Za-z0-9_-])" % branch_key_number, tail):
            accepted.append("KAN-%d" % branch_key_number)
    return accepted


def _scan_hostlike(text: str, problems: List[Problem]) -> None:
    """Scheme-less look-alikes such as 'liferescue.atlassian.net.evil.com/browse/KAN-20'."""
    for match in _HOSTLIKE.finditer(text):
        token = match.group(0).lower()
        if token == JIRA_HOST:
            continue  # HOSTLIKE_GUARD
        if (
            "atlassian.net" in token
            or token.startswith("liferescue.")
            or "liferescue." in token
            or "liferescue-" in token
        ):
            problems.append(("LOOKALIKE_HOST", CODES["LOOKALIKE_HOST"]))


def check_pr_link(title: object, body: object, branch: object) -> PrLinkResult:
    """Return PrLinkResult(ok, key, problems, branch_note). Never raises; fails closed."""
    try:
        return _check(title, body, branch)
    except Exception:  # an unexpected failure is never an "ok"
        return PrLinkResult(False, None, (("INPUT_MALFORMED", CODES["INPUT_MALFORMED"]),), None)


def _check(title: object, body: object, branch: object) -> PrLinkResult:
    problems: List[Problem] = []
    bad_input = (
        _text_input_problem(title, MAX_TITLE, False),
        _text_input_problem(body, MAX_BODY, True),
        _text_input_problem(branch, MAX_BRANCH, False),
    )
    if any(bad_input):
        problems.append(("INPUT_MALFORMED", CODES["INPUT_MALFORMED"]))
        return PrLinkResult(False, None, tuple(problems), escaped(branch) if isinstance(branch, str) else None)
    assert isinstance(title, str) and isinstance(body, str) and isinstance(branch, str)

    # 1. branch
    why = _branch_problem(branch)
    if why == "UNAVAILABLE":
        problems.append(("BRANCH_VALIDATOR_UNAVAILABLE", CODES["BRANCH_VALIDATOR_UNAVAILABLE"]))
    elif why is not None:
        problems.append(("BRANCH_INVALID", CODES["BRANCH_INVALID"]))
    key_match = _KEY_IN_BRANCH.match(branch) if why is None else None
    if key_match is None:
        # still scan the text for look-alike hosts so that all problems are reported
        _scan_hostlike(title + "\n" + body, problems)
        _scan_urls(title + "\n" + body, 0, problems)
        return PrLinkResult(False, None, _dedupe(problems), escaped(branch))
    number = int(key_match.group(1))
    key = "KAN-%d" % number

    # 5. protected issues (proposed assumption)
    if number in PROTECTED_KAN_NUMBERS:
        problems.append(("PROTECTED_ISSUE", CODES["PROTECTED_ISSUE"]))

    # 4. hosts and URLs in title and body
    text = title + "\n" + body
    _scan_hostlike(text, problems)
    title_urls = _scan_urls(title, number, problems)
    body_urls = _scan_urls(body, number, problems)

    # 2. the branch key must be referenced in the title or the body
    in_title = any(int(n) == number for n in _KEY_TOKEN.findall(title))
    in_body = any(int(n) == number for n in _KEY_TOKEN.findall(body))
    if not (in_title or in_body or title_urls or body_urls):
        problems.append(("KEY_NOT_IN_TITLE_OR_BODY", CODES["KEY_NOT_IN_TITLE_OR_BODY"]))

    # 3. the body must carry the key (bare or in an accepted Jira URL)
    if not (in_body or body_urls):
        problems.append(("BODY_LACKS_JIRA_REFERENCE", CODES["BODY_LACKS_JIRA_REFERENCE"]))

    final = _dedupe(problems)
    return PrLinkResult(not final, key, final, None)


def _dedupe(problems: List[Problem]) -> Tuple[Problem, ...]:
    seen = []
    for item in problems:
        if item not in seen:
            seen.append(item)
    return tuple(seen)


# ---------------------------------------------------------------------------------------------
# command line
# ---------------------------------------------------------------------------------------------


def _read_inputs(environ: Mapping[str, str]) -> Tuple[Optional[Tuple[object, object, object]], Optional[str]]:
    """Return ((title, body, branch), None) or (None, usage_error_text). Texts are fixed strings."""
    path = environ.get(ENV_FILE)
    individual = [name for name in (ENV_TITLE, ENV_BODY, ENV_BRANCH) if name in environ]
    if path is not None:
        if individual:
            return None, "set either %s or the variables %s/%s/%s, not both" % (
                ENV_FILE,
                ENV_TITLE,
                ENV_BODY,
                ENV_BRANCH,
            )
        try:
            if os.path.getsize(path) > MAX_FILE_BYTES:
                return None, "the input file is too large"
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return None, "the input file cannot be read as JSON"
        if not isinstance(data, dict) or set(data) != {"title", "body", "branch"}:
            return None, 'the input file must be a JSON object with exactly the keys "title", "body", "branch"'
        body = "" if data["body"] is None else data["body"]  # GitHub sends null for an empty body
        return (data["title"], body, data["branch"]), None
    missing = [name for name in (ENV_TITLE, ENV_BODY, ENV_BRANCH) if name not in environ]
    if missing:
        return None, "set the environment variables %s, %s and %s (or %s)" % (ENV_TITLE, ENV_BODY, ENV_BRANCH, ENV_FILE)
    return (environ[ENV_TITLE], environ[ENV_BODY], environ[ENV_BRANCH]), None


def main(argv: Optional[Sequence[str]] = None, environ: Optional[Mapping[str, str]] = None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    environ = os.environ if environ is None else environ
    # No option parsing at all: any argument is refused without being looked at or printed.
    if argv:
        print("error: this script takes no arguments; see docs/pr-jira-link-check.md", file=sys.stderr)
        return 2
    inputs, usage = _read_inputs(environ)
    if inputs is None:
        print("error: " + str(usage), file=sys.stderr)
        return 2
    result = check_pr_link(*inputs)
    if result.ok:
        print("OK: PR is linked to Jira issue %s" % result.key)
        return 0
    for code, text in result.problems:
        print("INVALID %s: %s" % (code, text), file=sys.stderr)
    if result.branch_note is not None:
        print("branch (escaped): " + result.branch_note, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
