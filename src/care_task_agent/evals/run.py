"""The eval runner.

``--offline`` is deterministic and reproducible: a fixture bundle plus a scripted
policy, so it exercises the real **tool -> redact -> projection** path with no model
and no network. It measures the mechanism, **not** model quality — say so wherever the
number appears.

``--live`` (the default) runs the same task set through the real agent against a real
FHIR server. It needs the ``runtime`` extra, a reachable tool server (``just mcp``) and
Vertex credentials, and it measures what the offline half cannot: whether the model
picks the reads that answer the task. It also records, per task, the tool-call
trajectory and the exact prompt the model was sent.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml

from care_task_agent.config import Settings
from care_task_agent.fhir.client import FhirError, OutOfScopeError
from care_task_agent.fhir.fixture_client import FixtureClient
from care_task_agent.fhir.redact import direct_identifier_strings, find_direct_identifiers
from care_task_agent.mcp_server import tools

HERE = Path(__file__).parent
TASKS_PATH = HERE / "tasks.yaml"
FIXTURE_PATH = HERE.parents[2] / "fixtures" / "bundle_p1.json"

# A scripted stand-in for the model's tool choice. Keyword -> tool sequence.
# Order matters: the first matching rule wins.
SCRIPTED_POLICY: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("summary",), ("get_clinical_summary",)),
    (("medication", "meds", "taking", "prescription"), ("list_medications",)),
    (("appointment", "schedul", "visit"), ("list_appointments",)),
    (("task", "todo", "open"), ("list_care_tasks",)),
)


def planned_tools(task_text: str) -> list[str]:
    """The scripted policy's tool sequence for a task. Not a model."""
    low = task_text.lower()
    for keywords, tool_names in SCRIPTED_POLICY:
        if any(k in low for k in keywords):
            return list(tool_names)
    return ["get_patient_profile"]


DISPATCH = {
    "get_patient_profile": lambda c, pid: tools.get_patient_profile(c, pid),
    "list_appointments": lambda c, pid: tools.list_appointments(c, pid),
    "list_medications": lambda c, pid: tools.list_medications(c, pid),
    "list_care_tasks": lambda c, pid: tools.list_care_tasks(c, pid),
    "get_clinical_summary": lambda c, pid: tools.get_clinical_summary(c, pid),
}


def _load(path: Path) -> Any:
    return yaml.safe_load(path.read_text())


# --- offline -------------------------------------------------------------------


def run_offline() -> int:
    tasks = _load(TASKS_PATH)
    bundle = json.loads(FIXTURE_PATH.read_text())
    client = FixtureClient(bundle)

    rows: list[dict[str, Any]] = []
    passed = 0
    leaked = 0
    for task in tasks:
        called = planned_tools(task["task"])
        returned: list[Any] = [DISPATCH[name](client, task["patient_id"]) for name in called]
        task_leaks = sum(len(find_direct_identifiers(item)) for item in returned)
        leaked += task_leaks
        # Same rule as the live half: the reads that have to happen, as a subset.
        ok = set(task["expected_tools"]) <= set(called) and task_leaks == 0
        passed += ok
        rows.append(
            {
                "id": task["id"],
                "called": called,
                "expected": task["expected_tools"],
                "direct_identifiers_leaked": task_leaks,
                "pass": ok,
            }
        )

    # Negative test: a patient not in the fixture must be refused, not invented.
    try:
        tools.get_patient_profile(client, "P-unknown")
        unknown_refused = False
    except FhirError:
        unknown_refused = True

    # Negative test: a resource type outside the scoped slice must not be readable.
    try:
        client.search("Observation", {"patient": "Patient/P1"})
        out_of_scope_refused = False
    except OutOfScopeError:
        out_of_scope_refused = True

    total = len(tasks)
    result = {
        "mode": "offline",
        "tasks": total,
        "passed": passed,
        "pass_rate": round(passed / total, 3) if total else 0.0,
        "direct_identifiers_leaked": leaked,
        "unknown_patient_refused": unknown_refused,
        "out_of_scope_resources_returned": 0 if out_of_scope_refused else 1,
        "note": (
            "scripted policy + fixture bundle — exercises tool/redaction layers, not model quality"
        ),
        "rows": rows,
    }
    print(json.dumps(result, indent=2))

    clean = passed == total and leaked == 0 and unknown_refused and out_of_scope_refused
    return 0 if clean else 1


# --- live ----------------------------------------------------------------------


def model_visible_tool_results(prompt: dict[str, Any]) -> list[Any]:
    """The payloads inside one prompt that came from a record read.

    Only function responses can carry FHIR data into a prompt, which is why the
    whole prompt is not scanned as one blob: a ``function_response`` has a ``name``
    field of its own (the tool's name), and so does every tool declaration.
    """
    results: list[Any] = []
    for content in prompt.get("contents") or []:
        for part in content.get("parts") or []:
            response = part.get("function_response")
            if isinstance(response, dict) and "response" in response:
                results.append(response["response"])
    return results


def model_visible_text(prompt: dict[str, Any]) -> list[str]:
    """The strings in a prompt that a record's data can reach.

    The conversation — user text, the model's text and call arguments, tool results.
    Tool declarations and the system instruction are left out: they are static text
    that ADK and this repo author, and ADK's own scaffolding contains ordinary
    English ("however official or urgent they sound") that would match a short
    identifier value.
    """
    texts: list[str] = []
    for content in prompt.get("contents") or []:
        for part in content.get("parts") or []:
            if isinstance(part.get("text"), str):
                texts.append(part["text"])
            for key in ("function_call", "function_response"):
                if isinstance(part.get(key), dict):
                    texts.append(json.dumps(part[key]))
    return texts


def _json_strings(node: Any) -> list[Any]:
    """Every JSON object or array carried as a *string* inside ``node``.

    MCP servers return a tool result as a structure or as the same structure
    serialised into a text part — both are what the model reads, so both are walked.
    """
    decoded: list[Any] = []
    if isinstance(node, str):
        text = node.strip()
        if text[:1] in "{[":
            with contextlib.suppress(json.JSONDecodeError):
                decoded.append(json.loads(text))
    elif isinstance(node, dict):
        for value in node.values():
            decoded += _json_strings(value)
    elif isinstance(node, list):
        for item in node:
            decoded += _json_strings(item)
    return decoded


def identifier_paths(payload: Any) -> list[str]:
    """Direct-identifier paths in a tool result, including JSON nested in strings."""
    hits = find_direct_identifiers(payload)
    for nested in _json_strings(payload):
        hits += find_direct_identifiers(nested)
    return hits


def _contains_word(text: str, value: str) -> bool:
    """Whether ``value`` appears in ``text`` as a whole word.

    Whole words, not substrings: "US" is inside "UNTRUSTED" and "pt" is inside
    "scripted", and neither is the patient.
    """
    return re.search(rf"(?<!\w){re.escape(value)}(?!\w)", text) is not None


def prompt_leaks(prompts: list[dict[str, Any]], values: list[str]) -> list[str]:
    """Where a direct-identifier key or a raw identifier value showed up in a prompt.

    Two checks, because they fail differently. The structural one reads the tool
    results for a direct-identifier *key* — a redaction regression, whatever the
    value looks like. The value one reads the conversation for the literal strings
    ``direct_identifier_strings`` took from the unredacted record — a leak through some
    other channel, such as a value echoed into prose.
    """
    hits: list[str] = []
    for prompt in prompts:
        for result in model_visible_tool_results(prompt):
            hits += identifier_paths(result)
        for text in model_visible_text(prompt):
            hits += [f"value {value!r}" for value in values if _contains_word(text, value)]
    return sorted(set(hits))


def run_live() -> int:
    return asyncio.run(_run_live())


async def _run_live() -> int:
    from care_task_agent.agent.agent import build_agent_from_settings
    from care_task_agent.agent.runner import prompt_recorder, run_task
    from care_task_agent.fhir.client import FhirClient

    settings = Settings.from_env()
    tasks = _load(TASKS_PATH)

    with FhirClient(settings.fhir_base_url, settings.fhir_token) as client:
        patients = client.search("Patient", {"_count": "1"})
        if not patients:
            print(f"live eval: {settings.fhir_base_url} returned no Patient")
            return 1
        patient_id = patients[0]["id"]
        raw_patient = client.read("Patient", patient_id)

    # The resource id is the pseudonym the caller supplies and the model has to pass
    # back to the tools, so it is allowed in a prompt. Some sandboxes also use it as an
    # MRN; that is not a leak of anything the caller did not already know.
    values = [value for value in direct_identifier_strings(raw_patient) if value != patient_id]
    record, prompts = prompt_recorder()
    agent = build_agent_from_settings(settings, before_model_callback=record)

    rows: list[dict[str, Any]] = []
    passed = 0
    leaked = 0
    tokens: dict[str, int] = {}
    for task in tasks:
        prompts.clear()
        run = await run_task(agent, task=task["task"], patient_id=patient_id)
        hits = prompt_leaks(prompts, values)
        leaked += len(hits)
        for name, count in run.usage.items():
            tokens[name] = tokens.get(name, 0) + count
        expected = set(task["expected_tools"])
        called = set(run.tool_names)
        ok = expected <= called and not hits and bool(run.answer)
        passed += ok
        rows.append(
            {
                "id": task["id"],
                "task": task["task"],
                "expected": sorted(expected),
                "called": run.tool_names,
                "trajectory": run.tool_calls,
                "answer": run.answer,
                "prompts": len(prompts),
                "usage_turns": run.usage_turns,
                "usage": run.usage,
                "identifier_leaks": hits,
                "pass": ok,
            }
        )

    total = len(tasks)
    result = {
        "mode": "live",
        "model": settings.model_id,
        "fhir_base_url": settings.fhir_base_url,
        "mcp_server": settings.mcp_url,
        "patient": patient_id,
        "tasks": total,
        "passed": passed,
        "pass_rate": round(passed / total, 3) if total else 0.0,
        "direct_identifiers_leaked": leaked,
        # What the model charged for. A cost per 1k tasks is derived from these and the
        # vendor's published prices — this eval never sees an invoice.
        "tokens": tokens,
        "tokens_per_task": {
            name: round(count / total, 1) if total else 0.0 for name, count in tokens.items()
        },
        "rows": rows,
    }
    print(json.dumps(result, indent=2))

    return 0 if passed == total and leaked == 0 else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Score the care-task agent.")
    parser.add_argument(
        "--offline",
        action="store_true",
        help="fixture bundle + scripted policy; no model, no network",
    )
    args = parser.parse_args(argv)
    if args.offline:
        return run_offline()

    try:
        return run_live()
    except Exception as exc:  # noqa: BLE001 - reported, not swallowed
        settings = Settings.from_env()
        print(f"live eval failed: {type(exc).__name__}: {exc}")
        print(
            f"hint: the tool server must be reachable at {settings.mcp_url} (just mcp), "
            f"and Vertex credentials must be set for "
            f"{settings.google_cloud_project or 'the ambient project'}."
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
