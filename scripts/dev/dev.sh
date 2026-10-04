#!/usr/bin/env bash
# make dev: start PostgreSQL (docker compose) and, when their scaffolds exist, apps/api and apps/web.
#
# Degrades gracefully while the apps are not merged yet:
#   * no docker             -> clear error (set SKIP_DB=1 to run the apps against your own PostgreSQL)
#   * no apps/api scaffold  -> message, API skipped
#   * no apps/web scaffold  -> message, web skipped
#   * neither app           -> database is started and left running; exit 0
# Ctrl-C stops the apps. The database container keeps running; stop it with `make down`.
#
# Expected conventions (proposed; override with API_CMD / WEB_CMD if LR 04 / LR 05 choose differently):
#   API: apps/api/app/main.py exposing `app` (FastAPI) -> python -m uvicorn app.main:app --reload
#   Web: apps/web/package.json with a `dev` script (Next.js)
# API_CMD / WEB_CMD are commands YOU put in your own environment or .env; they run in the app directory via bash -c.
set -euo pipefail
# shellcheck source=scripts/dev/common.sh
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

bash "${LR_ROOT}/scripts/dev/init-env.sh"
load_env "$LR_ENV_FILE"

API_HOST="${API_HOST:-127.0.0.1}"
API_PORT="${API_PORT:-8000}"
WEB_HOST="${WEB_HOST:-127.0.0.1}"
WEB_PORT="${WEB_PORT:-3000}"
API_DIR="${LR_ROOT}/apps/api"
WEB_DIR="${LR_ROOT}/apps/web"

# --- 1. database -------------------------------------------------------------------------------------------
if [[ "${SKIP_DB:-0}" == "1" ]]; then
  log "SKIP_DB=1: not starting PostgreSQL; expecting DATABASE_URL to point at a database you run yourself"
else
  if ! have docker || ! docker compose version >/dev/null 2>&1; then
    err "docker compose v2 is not available, so the database cannot be started."
    err "Install Docker, or run with SKIP_DB=1 and provide your own PostgreSQL via DATABASE_URL in .env."
    exit 1
  fi
  if ! docker info >/dev/null 2>&1; then
    err "the docker daemon is not reachable - start Docker and retry."
    exit 1
  fi
  log "starting PostgreSQL (127.0.0.1:${POSTGRES_HOST_PORT:-5432}) and waiting for its healthcheck ..."
  dc up -d --wait --wait-timeout 120 db
  log "PostgreSQL is healthy"
fi
derive_database_url

# --- 2. decide what can run --------------------------------------------------------------------------------
run_api=0
run_web=0
api_cmd=""
web_cmd=""

if [[ -n "${API_CMD:-}" && -d "$API_DIR" ]]; then
  run_api=1; api_cmd="$API_CMD"
elif [[ -f "${API_DIR}/app/main.py" ]]; then
  py="python3"
  [[ -x "${API_DIR}/.venv/bin/python" ]] && py="${API_DIR}/.venv/bin/python"
  if "$py" -c 'import uvicorn' >/dev/null 2>&1; then
    run_api=1
    api_cmd="\"$py\" -m uvicorn app.main:app --reload --host \"$API_HOST\" --port \"$API_PORT\""
  else
    warn "apps/api found but 'uvicorn' is not importable with ${py}. Run: make install-api   (API skipped)"
  fi
else
  log "apps/api scaffold not found (apps/api/app/main.py) - API skipped. It arrives with LR 04's scaffold PR."
fi

if [[ -n "${WEB_CMD:-}" && -d "$WEB_DIR" ]]; then
  run_web=1; web_cmd="$WEB_CMD"
elif [[ -f "${WEB_DIR}/package.json" ]]; then
  if [[ -d "${WEB_DIR}/node_modules" ]]; then
    pm="npm"
    [[ -f "${WEB_DIR}/pnpm-lock.yaml" ]] && have pnpm && pm="pnpm"
    [[ -f "${WEB_DIR}/yarn.lock" ]] && have yarn && pm="yarn"
    if have "$pm"; then
      run_web=1
      if [[ "$pm" == "npm" ]]; then
        web_cmd="npm run dev -- -H \"$WEB_HOST\" -p \"$WEB_PORT\""
      else
        web_cmd="$pm dev -H \"$WEB_HOST\" -p \"$WEB_PORT\""
      fi
    else
      warn "apps/web found but '${pm}' is not installed (web skipped)"
    fi
  else
    warn "apps/web found but dependencies are not installed. Run: make install-web   (web skipped)"
  fi
else
  log "apps/web scaffold not found (apps/web/package.json) - web skipped. It arrives with LR 05's PR."
fi

if [[ $run_api -eq 0 && $run_web -eq 0 ]]; then
  if [[ "${SKIP_DB:-0}" == "1" ]]; then
    log "no application to run and the database step was skipped - nothing to do"
  else
    log "no application to run. Database is up on 127.0.0.1:${POSTGRES_HOST_PORT:-5432}; stop it with: make down"
  fi
  exit 0
fi

# --- 3. run apps with prefixed output, one process group each ---------------------------------------------
set -m
pids=()
probe_pids=()
cleanup() {
  trap - EXIT INT TERM
  log "stopping apps ..."
  for p in "${pids[@]:-}" "${probe_pids[@]:-}"; do
    if [[ -n "$p" ]]; then kill -- "-$p" 2>/dev/null || true; fi
  done
  wait "${pids[@]:-}" 2>/dev/null || true
  if [[ "${SKIP_DB:-0}" == "1" ]]; then log "apps stopped"; else log "apps stopped; database still running (make down to stop it)"; fi
}
trap cleanup EXIT INT TERM

start() { # name dir cmd
  local name="$1" dir="$2" cmd="$3"
  log "starting ${name}: (cd ${dir#"$LR_ROOT"/} && ${cmd})"
  ( cd "$dir" && exec bash -c "$cmd" 2>&1 | sed -u "s/^/[${name}] /" ) &
  pids+=("$!")
}

probe() { # name url
  local name="$1" url="$2"
  have curl || return 0
  for _ in $(seq 1 60); do
    if curl -fsS --max-time 2 "$url" >/dev/null 2>&1; then log "${name} is up: ${url}"; return 0; fi
    sleep 1
  done
  warn "${name} did not answer at ${url} within 60s (it may still be starting, or may not expose this path yet)"
}

[[ $run_api -eq 1 ]] && start api "$API_DIR" "$api_cmd"
[[ $run_web -eq 1 ]] && start web "$WEB_DIR" "$web_cmd"
if [[ $run_api -eq 1 ]]; then probe api "http://${API_HOST}:${API_PORT}/api/health" & probe_pids+=("$!"); fi
if [[ $run_web -eq 1 ]]; then probe web "http://${WEB_HOST}:${WEB_PORT}/" & probe_pids+=("$!"); fi

log "running. Ctrl-C to stop. API http://${API_HOST}:${API_PORT}  Web http://${WEB_HOST}:${WEB_PORT}"
# Portable (bash 3.2 has no `wait -n`): poll until any app process group leader has exited.
while :; do
  for p in "${pids[@]}"; do
    if ! kill -0 "$p" 2>/dev/null; then
      log "an application process exited; shutting the others down"
      exit 0
    fi
  done
  sleep 1
done
