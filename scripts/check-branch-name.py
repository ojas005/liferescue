#!/usr/bin/env python3
"""Check that a Git branch name follows the LifeRescue rule (KAN-20).

Rule: <type>/KAN-<number>-<description>
  - <type> is one of feature, bugfix, security, chore, docs (lowercase)
  - <number> is a positive integer without leading zeros
  - <description> is lowercase letters and digits, words separated by single hyphens
  - total length is at most 100 characters

The branch name is read from the first command-line argument or, if there is no
argument, from the environment variable BRANCH_NAME (or the variable named with
--env-var). The name is treated as untrusted data: it is only compared with a fixed
pattern. It is never evaluated, never passed to a shell and never used to run a
command, and it is printed back only in escaped form.

Uses the Python standard library only; no network access, no subprocess calls.
Exit code 0 if the name is valid, 1 if it is invalid, 2 if no name was given.
"""
import argparse
import os
import re
import sys

PREFIXES = ("feature", "bugfix", "security", "chore", "docs")
MAX_LENGTH = 100
PATTERN = r"^(feature|bugfix|security|chore|docs)/KAN-[1-9][0-9]*-[a-z0-9]+(-[a-z0-9]+)*$"
BRANCH = re.compile(PATTERN)
DEFAULT_ENV_VAR = "BRANCH_NAME"


def validate(name):
    """Return None if `name` is valid, else a short reason (plain ASCII text)."""
    if not isinstance(name, str):
        return "branch name is not text"
    if name == "":
        return "branch name is empty"
    if len(name) > MAX_LENGTH:
        return f"branch name is {len(name)} characters; the maximum is {MAX_LENGTH}"
    # fullmatch: the whole string must match, so a trailing newline is rejected
    # (re's "$" alone would accept "name\n").
    if BRANCH.fullmatch(name) is None:
        return "branch name does not match the required pattern"
    return None


def escaped(name):
    """Printable, single-line, ASCII-only form of untrusted text (no control chars)."""
    return ascii(name)


def main(argv=None, environ=None):
    environ = os.environ if environ is None else environ
    parser = argparse.ArgumentParser(
        description="Validate a branch name: <type>/KAN-<number>-<description>."
    )
    parser.add_argument("branch", nargs="?", help="branch name to check")
    parser.add_argument(
        "--env-var",
        default=DEFAULT_ENV_VAR,
        help=f"environment variable to read when no argument is given (default {DEFAULT_ENV_VAR})",
    )
    args = parser.parse_args(argv)

    if args.branch is not None:
        name = args.branch
    elif args.env_var in environ:
        name = environ[args.env_var]
    else:
        print(
            f"error: no branch name given; pass it as an argument or set {args.env_var}",
            file=sys.stderr,
        )
        return 2

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
