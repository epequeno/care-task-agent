"""A ``FhirClient``-shaped double backed by a Bundle file.

For **tests and the offline eval only** — not for production. It lets the real
tool -> redact -> projection path run with no network, so half the gate is
reproducible in any checkout.
"""

from __future__ import annotations

from typing import Any

from care_task_agent.fhir.client import FhirError, require_in_scope


def _resource_reference(resource: dict[str, Any]) -> str | None:
    """The patient a resource points at, across the shapes FHIR uses for it."""
    for key in ("subject", "patient", "for"):
        ref = resource.get(key)
        if isinstance(ref, dict) and ref.get("reference"):
            return ref["reference"]
    for participant in resource.get("participant") or []:
        actor = participant.get("actor") if isinstance(participant, dict) else None
        if isinstance(actor, dict) and actor.get("reference"):
            return actor["reference"]
    return None


class FixtureClient:
    """Read/search over an in-memory Bundle. Accepts the same calls as FhirClient."""

    def __init__(self, bundle: dict[str, Any]) -> None:
        self._by_type: dict[str, list[dict[str, Any]]] = {}
        for entry in bundle.get("entry", []):
            resource = entry.get("resource")
            if not resource:
                continue
            self._by_type.setdefault(resource.get("resourceType", ""), []).append(resource)

    def __enter__(self) -> FixtureClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        return None

    def read(self, resource_type: str, resource_id: str) -> dict[str, Any]:
        require_in_scope(resource_type)
        for resource in self._by_type.get(resource_type, []):
            if resource.get("id") == resource_id:
                return resource
        raise FhirError(f"{resource_type}/{resource_id} not found in fixture")

    def search(
        self, resource_type: str, params: dict[str, str] | None = None
    ) -> list[dict[str, Any]]:
        require_in_scope(resource_type)
        params = params or {}
        wanted = params.get("patient")
        rows = self._by_type.get(resource_type, [])
        if not wanted:
            return list(rows)
        # Accept both `Patient/<id>` and bare `<id>`, matching the FHIR search forms.
        ref = wanted if wanted.startswith("Patient/") else f"Patient/{wanted}"
        return [r for r in rows if _resource_reference(r) == ref]
