#!/usr/bin/env bash
# Create .env from .env.example if it does not exist, with a random local POSTGRES_PASSWORD.
# Never overwrites an existing .env. Never prints the generated password.
set -euo pipefail
# shellcheck source=scripts/dev/common.sh
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

if [[ -f "$LR_ENV_FILE" ]]; then
  log ".env already exists - left unchanged"
  exit 0
fi
[[ -f "${LR_ROOT}/.env.example" ]] || { err ".env.example not found"; exit 1; }
have python3 || { err "python3 is required to generate a random local password (or copy .env.example to .env and edit it)"; exit 1; }

umask 077
python3 - "${LR_ROOT}/.env.example" "$LR_ENV_FILE" <<'PY'
import secrets
import sys

src, dst = sys.argv[1], sys.argv[2]
with open(src, encoding="utf-8") as f:
    text = f.read()
placeholder = "POSTGRES_PASSWORD=REPLACE_ME_LOCAL_ONLY"
if placeholder not in text:
    sys.exit("placeholder line not found in .env.example")
text = text.replace(placeholder, "POSTGRES_PASSWORD=" + secrets.token_hex(16))
with open(dst, "x", encoding="utf-8") as f:  # "x": fail if it appeared meanwhile
    f.write(text)
PY
log "created .env (mode 600) with a random local POSTGRES_PASSWORD; edit it for any other local settings"
