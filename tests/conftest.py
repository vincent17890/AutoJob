from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture
def fixture_json() -> Any:
    def _load(name: str) -> Any:
        path = Path(__file__).parent / "fixtures" / name
        return json.loads(path.read_text(encoding="utf-8"))

    return _load


@pytest.fixture
def fixture_text() -> Any:
    def _load(name: str) -> str:
        path = Path(__file__).parent / "fixtures" / name
        return path.read_text(encoding="utf-8")

    return _load
