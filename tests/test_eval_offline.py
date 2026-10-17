"""The offline eval must stay clean — this test is what keeps the number honest."""

from __future__ import annotations

import json

from care_task_agent.evals import run


def test_offline_eval_is_clean(capsys) -> None:
    assert run.run_offline() == 0
    result = json.loads(capsys.readouterr().out)
    assert result["mode"] == "offline"
    assert result["passed"] == result["tasks"]
    assert result["direct_identifiers_leaked"] == 0
    assert result["unknown_patient_refused"] is True
    assert result["out_of_scope_resources_returned"] == 0


def test_scripted_policy_matches_expectations() -> None:
    assert run.planned_tools("Which medications is the patient on?") == ["list_medications"]
    assert run.planned_tools("What appointments are coming up?") == ["list_appointments"]
    assert run.planned_tools("Are there any open care tasks?") == ["list_care_tasks"]
    assert run.planned_tools("Give me a full summary") == ["get_clinical_summary"]
    assert run.planned_tools("Is the patient active?") == ["get_patient_profile"]
