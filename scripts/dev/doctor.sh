#!/usr/bin/env bash
# Report which parts of the local stack can run on this machine. Exit 0 always (informational), 1 only on hard
# misconfiguration that would make `make dev` fail for everyone (compose file missing).
set -uo pipefail
# shellcheck source=scripts/dev/common.sh
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

ok()   { printf '  [ok]      %s\n' "$*"; }
miss() { printf '  [missing] %s\n' "$*"; }
skip() { printf '  [absent]  %s\n' "$*"; }

echo "LifeRescue local stack - environment check"
[[ -f "$LR_COMPOSE_FILE" ]] || { err "compose file missing: $LR_COMPOSE_FILE"; exit 1; }

if have docker && docker compose version >/dev/null 2>&1; then ok "docker compose ($(docker compose version --short 2>/dev/null))"; else miss "docker compose v2 - needed for the database (install Docker Desktop / Docker Engine + compose plugin)"; fi
if have docker && docker info >/dev/null 2>&1; then ok "docker daemon reachable"; else miss "docker daemon not reachable - start Docker"; fi
if have python3; then ok "python3 $(python3 --version 2>&1 | cut -d' ' -f2)"; else miss "python3 - needed for apps/api (3.11+ per packages/secrets README) and .env generation"; fi
if have node; then ok "node $(node --version)"; else miss "node - needed for apps/web"; fi
if have npm; then ok "npm $(npm --version)"; else miss "npm - needed for apps/web"; fi
if [[ -f "$LR_ENV_FILE" ]]; then ok ".env present"; else miss ".env - run: make env"; fi

if [[ -f "${LR_ROOT}/apps/api/app/main.py" ]]; then ok "apps/api scaffold found (app/main.py)"; else skip "apps/api scaffold (apps/api/app/main.py) - LR 04 PR not merged yet; 'make dev' will start only the database"; fi
if [[ -f "${LR_ROOT}/apps/web/package.json" ]]; then ok "apps/web scaffold found (package.json)"; else skip "apps/web scaffold (apps/web/package.json) - LR 05 PR not merged yet; 'make dev' will skip the web app"; fi
exit 0
