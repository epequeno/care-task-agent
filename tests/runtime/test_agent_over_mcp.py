"""The seam: ADK's MCP client against the real FastMCP server, with a scripted model.

Everything here is real except the model and the FHIR server: the tool server runs on
a loopback port and speaks MCP over streamable HTTP, the agent reaches it by URL, and
the tools read the fixture bundle. That is the one thing the rest of the suite cannot
check — whether the two frameworks actually speak to each other — and it is the risk
this artifact carries.

No model, no credentials, no network.
"""

from __future__ import annotations

import asyncio
import json
import socket
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastmcp")

import httpx  # noqa: E402
from google.adk.models import BaseLlm  # noqa: E402
from google.adk.models.llm_response import LlmResponse  # noqa: E402
from google.genai import types  # noqa: E402

from care_task_agent.agent.agent import build_agent  # noqa: E402
from care_task_agent.agent.runner import prompt_recorder, run_task  # noqa: E402
from care_task_agent.evals.run import prompt_leaks  # noqa: E402
from care_task_agent.fhir.fixture_client import FixtureClient  # noqa: E402
from care_task_agent.fhir.redact import direct_identifier_strings  # noqa: E402
from care_task_agent.mcp_server import server  # noqa: E402

ROOT = Path(__file__).parents[2]
BUNDLE: dict[str, Any] = json.loads((ROOT / "fixtures" / "bundle_p1.json").read_text())
PATIENT = "P1"


class ScriptedLlm(BaseLlm):
    """Calls one tool, then answers. Stands in for the model."""

    tool_name: str = "get_patient_profile"

    @classmethod
    def supported_models(cls) -> list[str]:
        return [r"scripted.*"]

    async def generate_content_async(self, llm_request: Any, stream: bool = False):
        answered = any(
            part.function_response
            for content in llm_request.contents or []
            for part in content.parts or []
        )
        if answered:
            parts = [types.Part(text="Answered from the records.")]
        else:
            call = types.FunctionCall(name=self.tool_name, args={"patient_id": PATIENT})
            parts = [types.Part(function_call=call)]
        yield LlmResponse(
            content=types.Content(role="model", parts=parts),
            # Fixed numbers per turn, so the run's summed usage is checkable.
            usage_metadata=types.GenerateContentResponseUsageMetadata(
                prompt_token_count=100,
                candidates_token_count=10,
                total_token_count=110,
            ),
        )


async def _wait_until_up(port: int) -> None:
    for _ in range(100):
        try:
            async with httpx.AsyncClient() as client:
                await client.get(f"http://127.0.0.1:{port}/mcp")
            return
        except httpx.HTTPError:
            await asyncio.sleep(0.05)
    raise TimeoutError(f"the tool server never came up on port {port}")


async def _run_over_mcp() -> Any:
    """Serve the tool server on a free loopback port and drive one task through it."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    mcp = server.build_server(lambda: FixtureClient(BUNDLE))
    serving = asyncio.create_task(
        mcp.run_async(transport="http", host="127.0.0.1", port=port, show_banner=False)
    )
    record, prompts = prompt_recorder()
    agent = build_agent(f"http://127.0.0.1:{port}/mcp", model="x", before_model_callback=record)
    agent.model = ScriptedLlm(model="scripted")
    try:
        await _wait_until_up(port)
        run = await run_task(agent, task="Is the patient active?", patient_id=PATIENT)
    finally:
        await agent.tools[0].close()
        serving.cancel()
    run.prompts = prompts
    return run


def test_the_agent_reads_through_the_tool_server() -> None:
    run = asyncio.run(_run_over_mcp())

    assert run.tool_names == ["get_patient_profile"]
    assert run.tool_calls[0]["args"] == {"patient_id": PATIENT}
    assert run.answer == "Answered from the records."


def test_token_usage_is_summed_across_turns_not_overwritten() -> None:
    """The figure `RESULTS.md` derives its cost from, checked against known turns."""
    run = asyncio.run(_run_over_mcp())

    assert run.usage_turns == 2, "the scripted run makes two model turns"
    assert run.usage_turns == len(run.prompts), "one usage report per recorded prompt"
    assert run.usage["prompt_token_count"] == 200
    assert run.usage["candidates_token_count"] == 20
    assert run.usage["total_token_count"] == 220


def test_nothing_the_model_read_identifies_the_patient() -> None:
    run = asyncio.run(_run_over_mcp())
    patient = next(
        entry["resource"]
        for entry in BUNDLE["entry"]
        if entry["resource"]["resourceType"] == "Patient"
    )

    assert run.prompts, "the prompt recorder saw no prompt"
    assert prompt_leaks(run.prompts, direct_identifier_strings(patient)) == []
