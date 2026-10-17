from __future__ import annotations

from typing import Any

import pytest

from care_task_agent.fhir.client import FhirError
from care_task_agent.fhir.fixture_client import FixtureClient
from care_task_agent.fhir.redact import find_direct_identifiers
from care_task_agent.mcp_server import tools


def test_profile_is_redacted(client: FixtureClient) -> None:
    profile = tools.get_patient_profile(client, "P1")
    assert profile["patient_id"] == "P1"
    assert find_direct_identifiers(profile) == []


def test_lists_filter_to_the_patient(client: FixtureClient) -> None:
    assert len(tools.list_appointments(client, "P1")) == 2
    assert len(tools.list_medications(client, "P1")) == 2
    assert len(tools.list_care_tasks(client, "P1")) == 2


def test_clinical_summary_carries_no_identifiers(client: FixtureClient) -> None:
    summary = tools.get_clinical_summary(client, "P1")
    assert find_direct_identifiers(summary) == []
    assert set(summary) == {"patient", "appointments", "medications", "tasks"}


def test_unknown_patient_is_refused(client: FixtureClient) -> None:
    with pytest.raises(FhirError):
        tools.get_patient_profile(client, "P-unknown")


def test_unknown_patient_is_refused_by_a_listing(client: FixtureClient) -> None:
    # The Patient is read before the listing, so nothing else is touched either.
    with pytest.raises(FhirError):
        tools.list_care_tasks(client, "P-unknown")


def test_free_text_that_names_the_patient_is_scrubbed(bundle: dict[str, Any]) -> None:
    """The case a public sandbox actually produced: a Task that names the patient."""
    bundle["entry"].append(
        {
            "resource": {
                "resourceType": "Task",
                "id": "T9",
                "status": "requested",
                "description": "Review appointment request from Jane Doe",
                "for": {"reference": "Patient/P1"},
            }
        }
    )
    tasks = tools.list_care_tasks(FixtureClient(bundle), "P1")

    descriptions = [task["description"] for task in tasks]
    assert "Review appointment request from" in descriptions
    assert not any("Doe" in description for description in descriptions if description)
    assert find_direct_identifiers(tasks) == []


def test_read_only_is_declared() -> None:
    assert tools.READ_ONLY is True
