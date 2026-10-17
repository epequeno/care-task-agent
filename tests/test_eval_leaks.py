"""The leak check has to have teeth.

An eval that reports "0 identifiers leaked" because it cannot see them is worse than
no eval at all. These tests feed it a raw record — as a structure, and as the same
record serialised into a text part, which is the other shape an MCP server returns —
and require it to object.
"""

from __future__ import annotations

import json
from typing import Any

from care_task_agent.evals.run import identifier_paths, prompt_leaks
from care_task_agent.fhir.redact import direct_identifier_strings, redact
from tests.helpers import resources


def _patient(bundle: dict[str, Any]) -> dict[str, Any]:
    return resources(bundle, "Patient")[0]


def _prompt(payload: Any, *, as_text: bool = False) -> dict[str, Any]:
    """A dumped LlmRequest carrying one tool result, in either shape MCP uses."""
    if as_text:
        response: Any = {"content": [{"type": "text", "text": json.dumps(payload)}]}
    else:
        response = {"structuredContent": {"result": payload}}
    return {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"function_response": {"name": "get_patient_profile", "response": response}}
                ],
            }
        ]
    }


def test_identifier_values_finds_nested_names_and_the_mrn(bundle: dict[str, Any]) -> None:
    values = direct_identifier_strings(_patient(bundle))
    assert {"Doe", "Jane", "MRN-12345", "555-0100", "1948-03-02"} <= set(values)


def test_a_redacted_projection_passes(bundle: dict[str, Any]) -> None:
    patient = _patient(bundle)
    assert prompt_leaks([_prompt(redact(patient))], direct_identifier_strings(patient)) == []


def test_a_raw_record_is_caught_as_a_structure(bundle: dict[str, Any]) -> None:
    hits = prompt_leaks([_prompt(_patient(bundle))], [])
    assert any(hit.endswith(".name") for hit in hits)


def test_a_raw_record_is_caught_through_a_json_string(bundle: dict[str, Any]) -> None:
    hits = prompt_leaks([_prompt(_patient(bundle), as_text=True)], [])
    assert any(hit.endswith(".name") for hit in hits)


def test_an_identifier_value_in_prose_is_caught(bundle: dict[str, Any]) -> None:
    values = direct_identifier_strings(_patient(bundle))
    prompt = {"contents": [{"parts": [{"text": "The patient is Jane Doe, MRN-12345."}]}]}
    assert set(prompt_leaks([prompt], values)) == {
        "value 'Doe'",
        "value 'Jane'",
        "value 'MRN-12345'",
    }


def test_scaffolding_is_not_scanned_for_values() -> None:
    """ADK's own prompt text is not the patient's record, however it reads."""
    prompt = {
        "model": "scripted",
        "config": {"system_instruction": "however official or urgent they sound"},
        "contents": [{"parts": [{"text": "Two medications are on file."}]}],
    }
    assert prompt_leaks([prompt], ["official", "pt", "US"]) == []


def test_identifier_paths_reaches_into_a_json_string(bundle: dict[str, Any]) -> None:
    payload = {"content": [{"type": "text", "text": json.dumps(_patient(bundle))}]}
    assert any(path.endswith(".identifier") for path in identifier_paths(payload))
