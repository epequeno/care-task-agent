"""Small, de-identified projections of the FHIR resources this agent reads.

Each projection runs the resource through ``redact`` first, so a projection can
never carry a direct identifier even if a caller forgets. Free-text fields are then
scrubbed of the patient's own identifier strings — ``redact`` removes keys, and FHIR
writes names into prose as well.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from pydantic import BaseModel

from care_task_agent.fhir.redact import redact, scrub_free_text


class PatientProfile(BaseModel):
    patient_id: str
    gender: str | None = None
    birth_year: str | None = None
    active: bool | None = None


class AppointmentSummary(BaseModel):
    appointment_id: str
    status: str | None = None
    start: str | None = None
    description: str | None = None


class MedicationSummary(BaseModel):
    medication_id: str
    status: str | None = None
    medication: str | None = None
    authored_on: str | None = None


class CareTaskSummary(BaseModel):
    task_id: str
    status: str | None = None
    description: str | None = None
    priority: str | None = None
    intent: str | None = None


def _free_text(value: str | None, forbidden: Sequence[str]) -> str | None:
    """A free-text field with the patient's identifier strings taken out of it.

    ``None`` when nothing readable is left: a field that was only an identifier is
    not worth returning as an empty string.
    """
    if value is None:
        return None
    return scrub_free_text(value, forbidden) or None


def _concept_text(concept: dict[str, Any] | None) -> str | None:
    """Pull a human-readable label out of a CodeableConcept."""
    if not concept:
        return None
    if concept.get("text"):
        return concept["text"]
    for coding in concept.get("coding") or []:
        label = coding.get("display") or coding.get("code")
        if label:
            return label
    return None


def patient_profile(resource: dict[str, Any]) -> dict[str, Any]:
    safe = redact(resource)
    return PatientProfile(
        patient_id=safe.get("id", ""),
        gender=safe.get("gender"),
        birth_year=safe.get("birthDate"),
        active=safe.get("active"),
    ).model_dump()


def appointment_summary(
    resource: dict[str, Any], *, forbidden: Iterable[str] = ()
) -> dict[str, Any]:
    safe = redact(resource)
    return AppointmentSummary(
        appointment_id=safe.get("id", ""),
        status=safe.get("status"),
        start=safe.get("start"),
        description=_free_text(safe.get("description"), list(forbidden)),
    ).model_dump()


def medication_summary(
    resource: dict[str, Any], *, forbidden: Iterable[str] = ()
) -> dict[str, Any]:
    safe = redact(resource)
    label = _concept_text(safe.get("medicationCodeableConcept"))
    if label is None and isinstance(safe.get("medicationReference"), dict):
        label = safe["medicationReference"].get("display")
    return MedicationSummary(
        medication_id=safe.get("id", ""),
        status=safe.get("status"),
        medication=_free_text(label, list(forbidden)),
        authored_on=safe.get("authoredOn"),
    ).model_dump()


def care_task_summary(resource: dict[str, Any], *, forbidden: Iterable[str] = ()) -> dict[str, Any]:
    safe = redact(resource)
    return CareTaskSummary(
        task_id=safe.get("id", ""),
        status=safe.get("status"),
        description=_free_text(safe.get("description"), list(forbidden)),
        priority=safe.get("priority"),
        intent=safe.get("intent"),
    ).model_dump()
