"""Shared fixtures: one synthetic patient bundle, loaded once per test."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from care_task_agent.fhir.fixture_client import FixtureClient

ROOT = Path(__file__).parents[1]
BUNDLE_PATH = ROOT / "fixtures" / "bundle_p1.json"


@pytest.fixture
def bundle() -> dict[str, Any]:
    return json.loads(BUNDLE_PATH.read_text())


@pytest.fixture
def client(bundle: dict[str, Any]) -> FixtureClient:
    return FixtureClient(bundle)
