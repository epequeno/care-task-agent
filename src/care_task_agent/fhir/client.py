"""A minimal FHIR R4 **read** client. Reads only, over httpx."""

from __future__ import annotations

from typing import Any

import httpx

FHIR_JSON = "application/fhir+json"

# The deliberately narrow scope: the four resource types the care tasks need.
# Enforced here, at the boundary that holds the token, so a new tool cannot widen
# the surface by accident. The scoped credential is the real limit; this is the
# local half of it, and it is what the negative test in the eval exercises.
READ_SCOPE: frozenset[str] = frozenset({"Patient", "Appointment", "MedicationRequest", "Task"})


class FhirError(RuntimeError):
    """A FHIR read failed, for a reason worth surfacing rather than swallowing."""


class OutOfScopeError(FhirError):
    """A read was attempted for a resource type outside the scoped slice."""


def require_in_scope(resource_type: str) -> None:
    """Refuse anything outside ``READ_SCOPE`` before a request is made."""
    if resource_type not in READ_SCOPE:
        raise OutOfScopeError(
            f"{resource_type!r} is out of scope; this client reads only {sorted(READ_SCOPE)}"
        )


class FhirClient:
    """Reads resources and searches. No writes, ever."""

    def __init__(
        self,
        base_url: str,
        token: str | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 15.0,
    ) -> None:
        headers = {"Accept": FHIR_JSON}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers=headers,
            timeout=timeout,
            transport=transport,
        )

    def __enter__(self) -> FhirClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def read(self, resource_type: str, resource_id: str) -> dict[str, Any]:
        require_in_scope(resource_type)
        response = self._client.get(f"/{resource_type}/{resource_id}")
        _raise_for_fhir(response)
        return response.json()

    def search(
        self, resource_type: str, params: dict[str, str] | None = None
    ) -> list[dict[str, Any]]:
        require_in_scope(resource_type)
        response = self._client.get(f"/{resource_type}", params=params or {})
        _raise_for_fhir(response)
        return _entries(response.json())


def _raise_for_fhir(response: httpx.Response) -> None:
    if response.status_code == 404:
        raise FhirError("not found")
    if response.status_code >= 400:
        raise FhirError(f"HTTP {response.status_code}: {response.text[:200]}")
    if "json" not in response.headers.get("content-type", ""):
        raise FhirError(f"unexpected content-type: {response.headers.get('content-type')!r}")


def _entries(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    if bundle.get("resourceType") != "Bundle":
        return []
    return [e["resource"] for e in bundle.get("entry", []) if "resource" in e]
