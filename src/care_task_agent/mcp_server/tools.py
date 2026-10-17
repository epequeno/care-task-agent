"""The read-only FHIR tools, as plain functions over a client.

Every function returns **redacted projections** — the model never sees a direct
identifier. There is no write path here, by design.

Each listing first reads the Patient, because a record's free text can name the
patient ("Review appointment request from Babara Rice" is a real Task from a public
sandbox) and the only way to know which strings to remove is to read them. It also
means an unknown patient is refused before any other resource is touched.
"""

from __future__ import annotations

from typing import Any, Protocol

from care_task_agent.fhir import models
from care_task_agent.fhir.redact import direct_identifier_strings


class ReadClient(Protocol):
    """The slice of FhirClient/FixtureClient these tools rely on."""

    def read(self, resource_type: str, resource_id: str) -> dict[str, Any]: ...

    def search(
        self, resource_type: str, params: dict[str, str] | None = None
    ) -> list[dict[str, Any]]: ...


TOOL_NAMES: tuple[str, ...] = (
    "get_patient_profile",
    "list_appointments",
    "list_medications",
    "list_care_tasks",
    "get_clinical_summary",
)

READ_ONLY = True


def _forbidden(client: ReadClient, patient_id: str) -> list[str]:
    """The patient's own identifier strings, to strip from any free text returned."""
    return direct_identifier_strings(client.read("Patient", patient_id))


def get_patient_profile(client: ReadClient, patient_id: str) -> dict[str, Any]:
    """De-identified profile: gender, birth year, active flag."""
    return models.patient_profile(client.read("Patient", patient_id))


def list_appointments(client: ReadClient, patient_id: str) -> list[dict[str, Any]]:
    return _appointments(client, patient_id, _forbidden(client, patient_id))


def list_medications(client: ReadClient, patient_id: str) -> list[dict[str, Any]]:
    return _medications(client, patient_id, _forbidden(client, patient_id))


def list_care_tasks(client: ReadClient, patient_id: str) -> list[dict[str, Any]]:
    return _care_tasks(client, patient_id, _forbidden(client, patient_id))


def get_clinical_summary(client: ReadClient, patient_id: str) -> dict[str, Any]:
    """One call that reads the four resource types the care tasks need."""
    patient = client.read("Patient", patient_id)
    forbidden = direct_identifier_strings(patient)
    return {
        "patient": models.patient_profile(patient),
        "appointments": _appointments(client, patient_id, forbidden),
        "medications": _medications(client, patient_id, forbidden),
        "tasks": _care_tasks(client, patient_id, forbidden),
    }


def _appointments(
    client: ReadClient, patient_id: str, forbidden: list[str]
) -> list[dict[str, Any]]:
    rows = client.search("Appointment", {"patient": f"Patient/{patient_id}", "_count": "20"})
    return [models.appointment_summary(r, forbidden=forbidden) for r in rows]


def _medications(client: ReadClient, patient_id: str, forbidden: list[str]) -> list[dict[str, Any]]:
    rows = client.search("MedicationRequest", {"patient": patient_id, "_count": "50"})
    return [models.medication_summary(r, forbidden=forbidden) for r in rows]


def _care_tasks(client: ReadClient, patient_id: str, forbidden: list[str]) -> list[dict[str, Any]]:
    rows = client.search("Task", {"patient": patient_id, "_count": "50"})
    return [models.care_task_summary(r, forbidden=forbidden) for r in rows]
