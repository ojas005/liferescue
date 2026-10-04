"""Discovery + registration of the simulated (MOCK_WRITE) tools that workflows bind to.

Workflow packages are data only (rule R4), so a workflow declares its simulated tools as plain
contract `ToolSpec` data in `app/workflows/<id>/tools.py::MOCK_TOOLS` (name, description, JSON
input_schema, side_effect=MOCK_WRITE). This module finds them generically (no workflow ids here)
and registers one labelled-simulation handler per spec. Nothing leaves the process.
"""

from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Sequence

from contract.errors import ConfigError
from contract.interfaces import ToolSpec
from contract.models import SideEffect

import app.workflows as _pkg

from .tools import RuntimeToolGateway, register_mock_write


def discover_mock_tools() -> list[ToolSpec]:
    """Collect `MOCK_TOOLS` from every `app.workflows.<id>.tools` module (names must be unique)."""
    found: list[ToolSpec] = []
    for mod in pkgutil.iter_modules(_pkg.__path__):
        if not mod.ispkg:
            continue
        name = f"{_pkg.__name__}.{mod.name}.tools"
        try:
            m = importlib.import_module(name)
        except ModuleNotFoundError as exc:
            if exc.name == name:
                continue
            raise
        found.extend(getattr(m, "MOCK_TOOLS", []))
    names = [t.name for t in found]
    if len(names) != len(set(names)):
        raise ConfigError("duplicate mock tool names across workflows")
    return found


def register_mock_tools(gateway: RuntimeToolGateway, specs: Sequence[ToolSpec]) -> None:
    for spec in specs:
        if spec.side_effect != SideEffect.MOCK_WRITE:
            raise ConfigError(f"tool {spec.name!r}: only mock_write tools may be declared as mocks")
        register_mock_write(
            gateway,
            spec.name,
            spec.description,
            input_schema=spec.input_schema,
            prefix=spec.name.upper().replace("_", "-"),
        )
