"""The MCP surface, in process: the tools the agent will discover, over the fixture.

Needs the ``runtime`` extra (``just test-runtime``). In-process — no port, no network —
so this is the cheap guard on the wiring the agent depends on.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastmcp")

from fastmcp import Client  # noqa: E402

from care_task_agent.fhir.fixture_client import FixtureClient  # noqa: E402
from care_task_agent.fhir.redact import find_direct_identifiers  # noqa: E402
from care_task_agent.mcp_server import server, tools  # noqa: E402

ROOT = Path(__file__).parents[2]
BUNDLE: dict[str, Any] = json.loads((ROOT / "fixtures" / "bundle_p1.json").read_text())


def _server():
    return server.build_server(lambda: FixtureClient(BUNDLE))


async def _list_tool_names(mcp: Any) -> list[str]:
    async with Client(mcp) as client:
        return sorted(tool.name for tool in await client.list_tools())


async def _call(mcp: Any, name: str, arguments: dict[str, Any]) -> Any:
    async with Client(mcp) as client:
        return (await client.call_tool(name, arguments)).data


def test_surface_is_exactly_the_read_only_tools() -> None:
    names = asyncio.run(_list_tool_names(_server()))
    assert names == sorted(tools.TOOL_NAMES)


def test_every_tool_carries_a_description_for_the_model() -> None:
    async def descriptions() -> list[str]:
        async with Client(_server()) as client:
            return [tool.description or "" for tool in await client.list_tools()]

    assert all(description.strip() for description in asyncio.run(descriptions()))


def test_profile_over_mcp_is_redacted() -> None:
    profile = asyncio.run(_call(_server(), "get_patient_profile", {"patient_id": "P1"}))
    assert profile["patient_id"] == "P1"
    assert find_direct_identifiers(profile) == []


def test_clinical_summary_over_mcp_carries_no_identifiers() -> None:
    summary = asyncio.run(_call(_server(), "get_clinical_summary", {"patient_id": "P1"}))
    assert find_direct_identifiers(summary) == []
    assert len(summary["appointments"]) == 2


def test_unknown_patient_is_an_error_not_an_empty_record() -> None:
    with pytest.raises(Exception, match="not found"):
        asyncio.run(_call(_server(), "get_patient_profile", {"patient_id": "P-unknown"}))
