"""Run one care task through the agent and record what it did.

Two things this exists to produce, because the gate asks for both:

* the **tool-call trajectory** — which reads the model chose, in order;
* the **exact prompt** the model was sent, so the "no direct identifiers in the
  prompt" claim can be checked against the payload rather than asserted
  (:func:`prompt_recorder` records it; the eval is what checks it).

``just demo`` runs one task from the command line; the service and the live eval
call :func:`run_task` directly.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass, field
from typing import Any

from google.adk.agents import LlmAgent
from google.adk.runners import InMemoryRunner
from google.genai import types

from care_task_agent.agent.agent import APP_NAME, build_agent_from_settings
from care_task_agent.config import Settings

USER_ID = "care-coordinator"

# What the model reports per turn. `total_token_count` is the vendor's own sum; the
# parts are kept because pricing differs for input and output.
_USAGE_FIELDS = (
    "prompt_token_count",
    "candidates_token_count",
    "thoughts_token_count",
    "total_token_count",
)


@dataclass
class TaskRun:
    """What the agent did for one task."""

    answer: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    prompts: list[dict[str, Any]] = field(default_factory=list)
    # Tokens the model reported, summed over model turns. `usage_turns` is the number
    # of turns that reported any, so a caller can check the sum is over the turns it
    # thinks it is (it should equal the number of recorded prompts).
    usage: dict[str, int] = field(default_factory=dict)
    usage_turns: int = 0

    @property
    def tool_names(self) -> list[str]:
        return [call["name"] for call in self.tool_calls]


def prompt_recorder() -> tuple[Any, list[dict[str, Any]]]:
    """A ``before_model_callback`` plus the list it appends each prompt to.

    The recorded value is the dumped ``LlmRequest``: the tool declarations, the
    conversation so far, and the tool results — everything the model is given.
    """
    prompts: list[dict[str, Any]] = []

    def record(_context: Any, llm_request: Any) -> None:
        prompts.append(llm_request.model_dump(exclude_none=True))
        return None

    return record, prompts


def _user_message(task: str, patient_id: str) -> types.Content:
    return types.Content(
        role="user",
        parts=[types.Part(text=f"Patient id: {patient_id}\nTask: {task}")],
    )


async def run_task(
    agent: LlmAgent,
    *,
    task: str,
    patient_id: str,
    app_name: str = APP_NAME,
) -> TaskRun:
    """Ask one question about one patient. Returns the answer and the trajectory."""
    runner = InMemoryRunner(agent=agent, app_name=app_name)
    session = await runner.session_service.create_session(app_name=app_name, user_id=USER_ID)

    run = TaskRun(answer="")
    answer_parts: list[str] = []
    async for event in runner.run_async(
        user_id=USER_ID,
        session_id=session.id,
        new_message=_user_message(task, patient_id),
    ):
        for call in event.get_function_calls():
            run.tool_calls.append({"name": call.name, "args": call.args or {}})
        usage = event.usage_metadata
        if usage is not None:
            run.usage_turns += 1
            for name in _USAGE_FIELDS:
                count = getattr(usage, name, None)
                if count:
                    run.usage[name] = run.usage.get(name, 0) + count
        if event.is_final_response() and event.content:
            for part in event.content.parts or []:
                if part.text:
                    answer_parts.append(part.text)

    run.answer = "\n".join(answer_parts).strip()
    return run


def _patient_id_from_sandbox(settings: Settings) -> str:
    """One patient id from the configured FHIR server, for the CLI to ask about."""
    from care_task_agent.fhir.client import FhirClient

    with FhirClient(settings.fhir_base_url, settings.fhir_token) as client:
        rows = client.search("Patient", {"_count": "1"})
    if not rows:
        raise SystemExit(f"no Patient returned by {settings.fhir_base_url}")
    return rows[0]["id"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ask the care-task agent one question.")
    parser.add_argument(
        "--task",
        default="Which medications is the patient currently taking?",
        help="the care coordinator's question",
    )
    parser.add_argument(
        "--patient",
        default=None,
        help="patient id; defaults to one patient from FHIR_BASE_URL",
    )
    args = parser.parse_args(argv)

    settings = Settings.from_env()
    patient_id = args.patient or _patient_id_from_sandbox(settings)
    agent = build_agent_from_settings(settings)
    run = asyncio.run(run_task(agent, task=args.task, patient_id=patient_id))

    print(f"patient: {patient_id}")
    print(f"task:    {args.task}")
    print("reads:")
    for call in run.tool_calls:
        print(f"  - {call['name']}({json.dumps(call['args'])})")
    print(f"answer:\n{run.answer}")
    return 0 if run.answer else 1


if __name__ == "__main__":
    sys.exit(main())
