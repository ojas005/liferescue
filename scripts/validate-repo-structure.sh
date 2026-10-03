#!/usr/bin/env bash
# Validates that the repository bootstrap structure is intact.
# Purpose: truthful, minimal structural check used by CI (doc 19 Step 2 skeleton).
set -euo pipefail

fail=0
require_file() { [[ -f "$1" ]] || { echo "MISSING FILE: $1"; fail=1; }; }
require_dir()  { [[ -d "$1" ]] || { echo "MISSING DIR:  $1"; fail=1; }; }

for f in LICENSE README.md CONTRIBUTING.md SECURITY.md CODEOWNERS .gitignore \
         .github/pull_request_template.md .github/workflows/ci.yml \
         docs/overview.md docs/adr/README.md docs/workforce/agent-registry.md \
         docs/baseline/manifest.json; do
  require_file "$f"
done

for d in apps services agents tools packages infrastructure tests scripts; do
  require_dir "$d"
  require_file "$d/README.md"
done

# Baseline manifest must list files that exist in docs/baseline/
if [[ -f docs/baseline/manifest.json ]]; then
  while IFS= read -r name; do
    require_file "docs/baseline/$name"
  done < <(python3 - <<'PY'
import json
for n in json.load(open("docs/baseline/manifest.json"))["documents"]:
    print(n)
PY
)
fi

if [[ $fail -ne 0 ]]; then
  echo "Repository structure validation FAILED"
  exit 1
fi
echo "Repository structure validation passed"
