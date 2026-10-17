from __future__ import annotations

import httpx
import pytest

from care_task_agent.fhir.client import FhirClient, FhirError

FHIR_JSON = {"content-type": "application/fhir+json"}


def _handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/fhir/Patient/P1":
        return httpx.Response(200, json={"resourceType": "Patient", "id": "P1"}, headers=FHIR_JSON)
    if request.url.path == "/fhir/Appointment":
        assert request.url.params["patient"] == "Patient/P1"
        return httpx.Response(
            200,
            json={
                "resourceType": "Bundle",
                "entry": [{"resource": {"resourceType": "Appointment", "id": "A1"}}],
            },
            headers=FHIR_JSON,
        )
    return httpx.Response(404, json={"resourceType": "OperationOutcome"}, headers=FHIR_JSON)


def _client() -> FhirClient:
    return FhirClient("https://sandbox.example/fhir", transport=httpx.MockTransport(_handler))


def test_read_returns_the_resource() -> None:
    with _client() as client:
        assert client.read("Patient", "P1")["id"] == "P1"


def test_search_unwraps_bundle_entries() -> None:
    with _client() as client:
        rows = client.search("Appointment", {"patient": "Patient/P1"})
    assert [r["id"] for r in rows] == ["A1"]


def test_404_raises_fhir_error() -> None:
    with _client() as client, pytest.raises(FhirError):
        client.read("Patient", "missing")


def test_bearer_token_is_sent() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization", "")
        return httpx.Response(200, json={"resourceType": "Patient", "id": "P1"}, headers=FHIR_JSON)

    with FhirClient("https://x/fhir", token="abc", transport=httpx.MockTransport(handler)) as c:
        c.read("Patient", "P1")
    assert seen["auth"] == "Bearer abc"
