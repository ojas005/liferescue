"""CLI runner for LifeRescue Evidence Intelligence evaluation benchmark."""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure project root is in sys.path
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from packages.domain.research_eval import format_markdown_report, run_evaluation


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    report = run_evaluation()
    md = format_markdown_report(report)
    out_file = _ROOT / "docs" / "submission" / "EVIDENCE_INTELLIGENCE_EVAL.md"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(md, encoding="utf-8")
    print(f"Report successfully generated at: {out_file}")
    print(md)
    if (
        not report["all_safety_invariants_passed"]
        or not report["all_injection_defenses_passed"]
    ):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
