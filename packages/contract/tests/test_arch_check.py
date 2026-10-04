from pathlib import Path

from contract.arch_check import scan_repo


def w(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def test_clean_tree_has_no_violations(tmp_path):
    w(tmp_path, "apps/api/app/runtime/model_gateway/nebius.py", "import httpx\nimport openai\n")
    w(tmp_path, "apps/api/app/runtime/tools/tavily.py", "import tavily\n")
    w(tmp_path, "apps/api/app/workflows/vehicle_breakdown/definition.py", "from contract.workflow_definition import WorkflowDefinition\n")
    w(tmp_path, "apps/api/app/runtime/engine.py", "from contract.interfaces import RunStore\n")
    w(tmp_path, "tests/e2e/test_x.py", "from contract.fakes import MockModel\nimport httpx\n")
    assert scan_repo(tmp_path) == []


def test_each_rule_catches_its_violation(tmp_path):
    w(tmp_path, "apps/api/app/agents2.py", "import langgraph\n")                                          # R1
    w(tmp_path, "apps/api/app/api/routes.py", "import httpx\n")                                            # R2
    w(tmp_path, "apps/api/app/main.py", "from contract.fakes import MockModel\n")                          # R3
    w(tmp_path, "apps/api/app/workflows/life_admin/definition.py", "import requests\n")                    # R4 (+R2)
    w(tmp_path, "apps/api/app/runtime/engine.py", "from app.db import session\n")                          # R5
    w(tmp_path, "apps/api/app/policy/engine.py", "from app.runtime import engine\n")                       # R6
    codes = {line.split()[0] for line in scan_repo(tmp_path)}
    assert codes == {"R1", "R2", "R3", "R4", "R5", "R6"}


def test_contract_package_itself_is_clean(tmp_path):
    import shutil
    src = Path(__file__).resolve().parent.parent
    shutil.copytree(src / "contract", tmp_path / "packages" / "contract" / "contract")
    shutil.copytree(src / "tests", tmp_path / "packages" / "contract" / "tests")
    assert scan_repo(tmp_path) == []
