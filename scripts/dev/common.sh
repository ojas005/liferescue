#!/usr/bin/env bash
# Shared helpers for the local-dev scripts. Source it; do not execute it.
# shellcheck shell=bash

# Repository root (this file lives in scripts/dev/).
LR_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LR_COMPOSE_FILE="${LR_ROOT}/infrastructure/docker-compose.yml"
LR_ENV_FILE="${LR_ROOT}/.env"

log()  { printf '[dev] %s\n' "$*"; }
warn() { printf '[dev] WARN: %s\n' "$*" >&2; }
err()  { printf '[dev] ERROR: %s\n' "$*" >&2; }

have() { command -v "$1" >/dev/null 2>&1; }

# Load KEY=VALUE lines from .env into the environment WITHOUT executing the file (no `source`, no eval).
# Existing environment variables win over the file. Values are taken literally (optional surrounding quotes
# stripped); comments and blank lines are skipped. Nothing is printed.
load_env() {
  local file="${1:-$LR_ENV_FILE}" line key val loaded=" "
  [[ -f "$file" ]] || return 0
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%$'\r'}"
    [[ "$line" =~ ^[[:space:]]*(#|$) ]] && continue
    [[ "$line" =~ ^[[:space:]]*([A-Za-z_][A-Za-z0-9_]*)=(.*)$ ]] || continue
    key="${BASH_REMATCH[1]}"
    val="${BASH_REMATCH[2]}"
    if [[ "$val" =~ ^\"(.*)\"$ ]] || [[ "$val" =~ ^\'(.*)\'$ ]]; then val="${BASH_REMATCH[1]}"; fi
    # Pre-existing environment wins over the file; within the file the last assignment wins.
    if [[ -z "${!key+x}" || "$loaded" == *" $key "* ]]; then
      export "$key=$val"
      loaded="${loaded}${key} "
    fi
  done <"$file"
}

# docker compose wrapper bound to the repo's compose file and root .env.
dc() { docker compose --env-file "$LR_ENV_FILE" -f "$LR_COMPOSE_FILE" "$@"; }

# Derive DATABASE_URL from the POSTGRES_* values when it is not set (password is URL-encoded; never printed).
derive_database_url() {
  [[ -n "${DATABASE_URL:-}" ]] && return 0
  have python3 || { warn "python3 not found; DATABASE_URL not derived (set it in .env)"; return 0; }
  DATABASE_URL="$(
    python3 - <<'PY'
import os
from urllib.parse import quote
u = quote(os.environ.get("POSTGRES_USER", "liferescue"), safe="")
p = quote(os.environ.get("POSTGRES_PASSWORD", ""), safe="")
h = os.environ.get("POSTGRES_HOST", "127.0.0.1")
port = os.environ.get("POSTGRES_HOST_PORT", "5432")
d = os.environ.get("POSTGRES_DB", "liferescue")
print(f"postgresql://{u}:{p}@{h}:{port}/{d}")
PY
  )"
  export DATABASE_URL
}
