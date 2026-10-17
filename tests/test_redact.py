from __future__ import annotations

from typing import Any

from care_task_agent.fhir.redact import (
    direct_identifier_strings,
    find_direct_identifiers,
    redact,
    scrub_free_text,
)
from tests.helpers import resources


def _patient(bundle: dict[str, Any]) -> dict[str, Any]:
    return resources(bundle, "Patient")[0]


def test_raw_record_does_carry_identifiers(bundle: dict[str, Any]) -> None:
    assert find_direct_identifiers(_patient(bundle))


def test_redact_removes_direct_identifiers(bundle: dict[str, Any]) -> None:
    safe = redact(_patient(bundle))
    assert find_direct_identifiers(safe) == []
    for key in ("name", "address", "telecom", "identifier"):
        assert key not in safe


def test_redact_generalises_birthdate(bundle: dict[str, Any]) -> None:
    assert redact(_patient(bundle))["birthDate"] == "1948"


def test_redact_keeps_clinical_fields_and_pseudonym(bundle: dict[str, Any]) -> None:
    safe = redact(_patient(bundle))
    assert safe["gender"] == "female"
    assert safe["id"] == "P1"


def test_redact_does_not_mutate_the_input(bundle: dict[str, Any]) -> None:
    raw = _patient(bundle)
    redact(raw)
    assert raw["name"][0]["family"] == "Doe"


def test_find_direct_identifiers_reports_paths(bundle: dict[str, Any]) -> None:
    hits = find_direct_identifiers(_patient(bundle))
    assert "$.name" in hits
    assert "$.identifier" in hits


def test_direct_identifier_strings_finds_what_the_keys_do_not_hold(
    bundle: dict[str, Any],
) -> None:
    values = direct_identifier_strings(_patient(bundle))
    # The name is under family/given, not under a key called "name".
    assert {"Doe", "Jane", "555-0100", "MRN-12345", "1 Main St", "1948-03-02"} <= set(values)


def test_direct_identifier_strings_ignores_a_pseudonym(bundle: dict[str, Any]) -> None:
    # `subject.reference` is the id the tools are called with, not a direct identifier.
    medication = resources(bundle, "MedicationRequest")[0]
    assert direct_identifier_strings({"subject": medication["subject"]}) == []


def test_scrub_free_text_removes_a_name_and_leaves_the_rest() -> None:
    scrubbed = scrub_free_text("Review appointment request from Babara Rice", ["Babara", "Rice"])
    assert scrubbed == "Review appointment request from"


def test_scrub_free_text_matches_whole_words_only() -> None:
    assert scrub_free_text("Briceno follow-up", ["Rice"]) == "Briceno follow-up"


def test_scrub_free_text_leaves_clean_text_alone() -> None:
    assert scrub_free_text("Annual wellness visit", ["Babara", "Rice"]) == "Annual wellness visit"


def test_scrub_free_text_is_empty_when_only_the_identifier_was_there() -> None:
    assert scrub_free_text("Babara Rice", ["Babara", "Rice"]) == ""
