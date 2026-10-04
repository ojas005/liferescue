from __future__ import annotations

from dataclasses import dataclass

from contract.interfaces import RunEngine
from fastapi import Request

from app.ports import Ports
from app.settings import Settings


@dataclass(frozen=True)
class Container:
    settings: Settings
    ports: Ports
    engine: RunEngine


def get_container(request: Request) -> Container:
    c: Container = request.app.state.container
    return c
