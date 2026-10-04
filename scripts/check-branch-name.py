#!/usr/bin/env python3
"""Check that a Git branch name follows the LifeRescue rule (KAN-20).

Rule: <type>/KAN-<number>-<description>
  - <type> is one of feature, bugfix, security, chore, docs (lowercase)
  - <number> is a positive integer without leading zeros
  - <description> is lowercase letters and digits, words separated by single hyphens
  - total length is at most 100 characters

The branch name is read ONLY from the environment variable BRANCH_NAME. The script has no
command-line options and takes no arguments: any argument (including -h, --help and --) is a
usage error (exit 2) and is never echoed. The variable name is fixed in the code, so the script
cannot be made to read or print any other environment variable. The name is treated as untrusted
data: it is only compared with a fixed pattern. It is never evaluated, never passed to a shell and
never used to run a command, and it is printed back only in escaped, length-bounded form.

Matching uses re.fullmatch on the exact string with no normalization. fullmatch is used because a
"$" anchor alone would accept a trailing newline in some engines (Perl/PCRE, Python re.match and
re.search, line-based grep); the fullmatch call rejects a name followed by a newline. The pattern keeps its "^" and "$"
anchors so it stays equal to the reference regular expression in CONTRIBUTING.md.

Uses the Python standard library only; no network access, no subprocess calls.
Exit code 0 if the name is valid, 1 if it is invalid (an empty value is invalid), 2 if BRANCH_NAME
is not set or any argument was given. A CI step must treat ANY non-zero exit code as failure.
"""
import os
import re
import sys

PREFIXES = ("feature", "bugfix", "security", "chore", "docs")
MAX_LENGTH = 100
PATTERN = r"^(feature|bugfix|security|chore|docs)/KAN-[1-9][0-9]*-[a-z0-9]+(-[a-z0-9]+)*$"
BRANCH = re.compile(PATTERN)
ENV_VAR = "BRANCH_NAME"  # fixed on purpose: never configurable from the command line
ECHO_LIMIT = 120  # at most this many characters of a name are echoed back


def validate(name):
    """Return None if `name` is valid, else a short reason (plain ASCII text)."""
    if not isinstance(name, str):
        return "branch name is not text"
    if name == "":
        return "branch name is empty"
    if len(name) > MAX_LENGTH:
        return f"branch name is {len(name)} characters; the maximum is {MAX_LENGTH}"
    # fullmatch (not match/search): the WHOLE string must match. A "$" anchor alone would
    # accept a trailing newline in some engines (Perl/PCRE, Python re.match/re.search,
    # line-based grep), so "feature/KAN-20-x\n" would pass. No Unicode normalization (NFKC
    # etc.) is applied either: full-width digits/letters and look-alikes are rejected as given.
    if BRANCH.fullmatch(name) is None:
        return "branch name does not match the required pattern"
    return None


def escaped(name):
    """Printable, single-line, ASCII-only, length-bounded form of untrusted text (no control chars)."""
    if len(name) > ECHO_LIMIT:
        return ascii(name[:ECHO_LIMIT]) + f"... [truncated; {len(name)} characters in total]"
    return ascii(name)


def main(argv=None, environ=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    environ = os.environ if environ is None else environ

    # No option parsing at all. Any argument is refused without being looked at or printed, so an
    # option-like argument (for example -h, --help or "--") can neither redirect the script to
    # another environment variable nor produce a success exit code.
    if argv:
        print(f"error: this script takes no arguments; set the environment variable {ENV_VAR}", file=sys.stderr)
        return 2
    if ENV_VAR not in environ:
        print(f"error: no branch name given; set the environment variable {ENV_VAR}", file=sys.stderr)
        return 2
    name = environ[ENV_VAR]

    reason = validate(name)
    if reason is None:
        print(f"OK: branch name {escaped(name)} is valid")
        return 0

    print(f"INVALID: {reason}: {escaped(name)}", file=sys.stderr)
    print("Required form: <type>/KAN-<number>-<description>", file=sys.stderr)
    print(f"Allowed prefixes: {', '.join(PREFIXES)}", file=sys.stderr)
    print(
        "<number> is a positive integer without leading zeros; <description> is lowercase "
        f"a-z, 0-9 and single hyphens; maximum length {MAX_LENGTH} characters.",
        file=sys.stderr,
    )
    print(f"Pattern: {PATTERN}", file=sys.stderr)
    print("Example: feature/KAN-20-jira-git-integration", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
