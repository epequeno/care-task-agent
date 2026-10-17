"""The read scope: a deliberately narrow slice, enforced before any request goes out.

This is the negative test the gate names — out-of-scope resources must be refused, and
the refusal must happen locally rather than by asking the server and hoping.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from care_task_agent.fhir.client import READ_SCOPE, FhirClient, FhirError, OutOfScopeError
from care_task_agent.fhir.fixture_client import FixtureClient

FHIR_JSON = {"content-type": "application/fhir+json"}


def test_scope_is_the_four_types_the_care_tasks_need() -> None:
    assert sorted(READ_SCOPE) == ["Appointment", "MedicationRequest", "Patient", "Task"]


def test_out_of_scope_read_is_refused_before_the_request() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(200, json={}, headers=FHIR_JSON)

    with FhirClient("https://sandbox.example/fhir", transport=httpx.MockTransport(handler)) as c:
        with pytest.raises(OutOfScopeError):
            c.read("Observation", "O1")
        with pytest.raises(OutOfScopeError):
            c.search("Condition", {"patient": "Patient/P1"})
    assert seen == []


def test_out_of_scope_error_is_still_a_fhir_error() -> None:
    # Callers that already handle a failed read keep working.
    assert issubclass(OutOfScopeError, FhirError)


def test_fixture_client_enforces_the_same_scope(bundle: dict[str, Any]) -> None:
    client = FixtureClient(bundle)
    with pytest.raises(OutOfScopeError):
        client.search("Observation", {"patient": "Patient/P1"})
    assert client.search("Patient", {"_count": "1"})
