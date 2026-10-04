"""Shared fixtures for cross-cutting tests (tests/conformance, later tests/e2e and tests/eval).

`stack_factory` / `stack` select the system under test with env LR_STACK=fake|real (default fake).
Production code never imports anything from tests/.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from lr_support.stack import FakeStack, make_stack_factory, selected_kind

VEHICLE_INPUT = {
    "description": "My car stopped on the highway and will not restart",
    "location": "Pune",
    "vehicle": "Hyundai i20",
}


def pytest_configure(config: pytest.Config) -> None:
    selected_kind()  # fail fast and clearly on an invalid LR_STACK instead of erroring in every test


def pytest_report_header(config: pytest.Config) -> str:
    return f"LifeRescue conformance: LR_STACK={selected_kind()}"


@pytest.fixture(scope="session")
def stack_kind() -> str:
    return selected_kind()


@pytest.fixture
def stack_factory(stack_kind: str) -> Callable[..., FakeStack]:
    """Build a stack with optional `definitions=[...]` and `model=...` (fake stack: MockModel by default)."""
    return make_stack_factory(stack_kind)


@pytest.fixture
def stack(stack_factory: Callable[..., FakeStack]) -> FakeStack:
    return stack_factory()


@pytest.fixture
def vehicle_input() -> dict[str, Any]:
    return dict(VEHICLE_INPUT)
