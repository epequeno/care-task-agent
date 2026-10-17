from __future__ import annotations

from typing import Any

from care_task_agent.fhir import models
from tests.helpers import resources


def test_patient_profile_is_de_identified(bundle: dict[str, Any]) -> None:
    profile = models.patient_profile(resources(bundle, "Patient")[0])
    assert profile["patient_id"] == "P1"
    assert profile["birth_year"] == "1948"
    assert profile["gender"] == "female"
    assert "name" not in profile


def test_medication_summary_reads_text_or_coding(bundle: dict[str, Any]) -> None:
    meds = {m["id"]: models.medication_summary(m) for m in resources(bundle, "MedicationRequest")}
    assert meds["M1"]["medication"] == "Lisinopril 10 mg"  # from `text`
    assert meds["M2"]["medication"] == "Metformin"  # from coding[0].display


def test_care_task_summary(bundle: dict[str, Any]) -> None:
    tasks = {t["id"]: models.care_task_summary(t) for t in resources(bundle, "Task")}
    assert tasks["T1"]["priority"] == "urgent"
    assert tasks["T1"]["status"] == "requested"


def test_appointment_summary(bundle: dict[str, Any]) -> None:
    appts = {a["id"]: models.appointment_summary(a) for a in resources(bundle, "Appointment")}
    assert appts["A1"]["status"] == "booked"
    assert appts["A2"]["status"] == "cancelled"
