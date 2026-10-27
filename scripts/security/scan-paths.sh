#!/usr/bin/env bash
# PROPOSED (LR 08 draft, not approved/applied): scan files or a directory for secrets BEFORE content is sent anywhere
# (API connector write, PR body, Jira/Confluence comment, chat). Intended for agents that do not run git hooks.
#
# Usage:  scripts/security/scan-paths.sh <file-or-dir> [<file-or-dir> ...]
#         printf '%s' "$TEXT" | scripts/security/scan-paths.sh -        # scan text from stdin (PR body, comment, etc.)
# Exit:   0 = no finding, 1 = finding or error (fail closed). A finding must stop the task and escalate (doc 16 s13).
set -euo pipefail

PINNED_VERSION="8.30.1"
ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
CONFIG="${GITLEAKS_CONFIG:-$ROOT/.gitleaks.toml}"

command -v gitleaks >/dev/null 2>&1 || { echo "scan-paths: gitleaks not found (pinned v${PINNED_VERSION})" >&2; exit 1; }
have="$(gitleaks version 2>/dev/null | tr -d 'v' | awk '{print $NF}')"
[ "$have" = "$PINNED_VERSION" ] || { echo "scan-paths: gitleaks $have found, expected $PINNED_VERSION" >&2; exit 1; }
[ -f "$CONFIG" ] || { echo "scan-paths: config $CONFIG missing" >&2; exit 1; }
[ "$#" -ge 1 ] || { echo "usage: scan-paths.sh <path>... | -" >&2; exit 1; }

status=0
for target in "$@"; do
  if [ "$target" = "-" ]; then
    tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
    cat > "$tmp/stdin.txt"
    gitleaks dir --config "$CONFIG" --redact --no-banner --exit-code 1 "$tmp" || status=1
  else
    gitleaks dir --config "$CONFIG" --redact --no-banner --exit-code 1 "$target" || status=1
  fi
done
[ "$status" -eq 0 ] || echo "scan-paths: possible secret found (redacted above). Do not send this content. Stop and escalate." >&2
exit "$status"
