"""Static ONE-runtime checks for the daily architecture review / CI. `python -m contract.arch_check <repo_root>` exits 1 on violations.

Scope is deliberately small (imports only). It does not replace review; it catches the usual drifts cheaply.
Rules (paths relative to repo root, POSIX):
  R1 no second orchestrator/agent framework anywhere (langgraph, langchain, crewai, autogen, llama_index, semantic_kernel, ...)
  R2 LLM / network client libs only in the model gateway, the tools package, or credential_broker (apps/api + packages/ + apps/ python)
  R3 contract.fakes / MockModel only imported from tests/ (or packages/contract itself)
  R4 apps/api/app/workflows/** may import only `contract` and stdlib (definitions are data, no logic dependencies)
  R5 apps/api/app/runtime must not import the HTTP layer (app.api) or the DB layer (app.db) directly (ports only)
  R6 policy/approvals/audit/db must not import app.runtime (no back-edges)
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ORCHESTRATORS = {"langgraph", "langchain", "langchain_core", "langchain_community", "crewai", "autogen", "autogen_agentchat", "llama_index",
                 "semantic_kernel", "haystack", "smolagents", "agno", "dspy", "pydantic_ai", "openai_agents", "agents"}
NETWORK_LIBS = {"openai", "tavily", "httpx", "requests", "aiohttp", "urllib3", "anthropic", "nebius", "websockets"}
NETWORK_ALLOWED = ("apps/api/app/runtime/model_gateway/", "apps/api/app/runtime/tools/", "packages/credential_broker/", "tests/",
                   "packages/contract/")
SKIP_PARTS = {"node_modules", ".venv", "venv", "__pycache__", ".git", ".next"}


def _imports(path: Path) -> list[tuple[str, int]]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return []
    out: list[tuple[str, int]] = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            out += [(a.name, n.lineno) for a in n.names]
        elif isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
            out.append((n.module, n.lineno))
    return out


def scan_repo(root: Path) -> list[str]:
    v: list[str] = []
    for p in sorted(root.rglob("*.py")):
        if SKIP_PARTS & set(p.parts):
            continue
        rel = p.relative_to(root).as_posix()
        for mod, line in _imports(p):
            top = mod.split(".")[0]
            where = f"{rel}:{line}"
            if top in ORCHESTRATORS and not rel.startswith("packages/contract/contract/arch_check"):
                v.append(f"R1 {where}: second orchestrator/agent framework '{mod}'")
            if top in NETWORK_LIBS and not rel.startswith(NETWORK_ALLOWED):
                v.append(f"R2 {where}: '{mod}' outside ModelGateway/ToolGateway/credential_broker")
            if (mod.startswith("contract.fakes") or mod.startswith("contract.fixtures")) and not rel.startswith(("tests/", "packages/contract/")):
                if not rel.startswith("apps/api/tests/"):
                    v.append(f"R3 {where}: test double '{mod}' imported by non-test code")
            if rel.startswith("apps/api/app/workflows/") and top not in {"contract", "__future__", "typing", "dataclasses", "enum", "datetime", "app"}:
                v.append(f"R4 {where}: workflow definitions may import only 'contract' (got '{mod}')")
            if rel.startswith("apps/api/app/workflows/") and top == "app" and not mod.startswith("app.workflows"):
                v.append(f"R4 {where}: workflow definitions must not import '{mod}'")
            if rel.startswith("apps/api/app/runtime/") and (mod.startswith("app.api") or mod.startswith("app.db")):
                v.append(f"R5 {where}: runtime imports '{mod}' (use the RunStore/ports instead)")
            if rel.startswith(("apps/api/app/policy/", "apps/api/app/approvals/", "apps/api/app/audit/", "apps/api/app/db/")) and mod.startswith("app.runtime"):
                v.append(f"R6 {where}: back-edge import of '{mod}'")
    return v


def main(argv: list[str]) -> int:
    root = Path(argv[1] if len(argv) > 1 else ".").resolve()
    violations = scan_repo(root)
    for line in violations:
        print(line)
    print(f"{len(violations)} violation(s)")
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
