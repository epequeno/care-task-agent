"""FastMCP server exposing the read-only FHIR tools.

Needs the ``runtime`` extra (``just sync-runtime``). ``just mcp`` runs it. It is a
separate process — and, deployed, a separate service — from the agent on purpose:
the FHIR token lives here, and this server is the only thing that holds it.

The agent consumes these tools over MCP by URL; it does not import them.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from fastmcp import FastMCP
from fastmcp.server.auth.providers.jwt import StaticTokenVerifier

from care_task_agent.config import Settings
from care_task_agent.fhir.client import FhirClient
from care_task_agent.mcp_server import tools

SERVER_NAME = "care-task-fhir"
AUTH_SCOPE = "fhir.read"


class ManagedClient(tools.ReadClient, Protocol):
    """A read client that owns a connection, so a call can open and close it."""

    def __enter__(self) -> Any: ...

    def __exit__(self, *_: object) -> None: ...


ClientFactory = Callable[[], ManagedClient]


def build_server(
    client_factory: ClientFactory, *, auth: StaticTokenVerifier | None = None
) -> FastMCP:
    """The tool server, over one client factory.

    ``client_factory`` is called per tool call: no connection is shared between
    calls, so one call cannot leave a client open for the next.
    """
    mcp = FastMCP(SERVER_NAME, auth=auth)

    @mcp.tool
    def get_patient_profile(patient_id: str) -> dict[str, Any]:
        """Read one patient's de-identified profile (no name, contact or identifiers)."""
        with client_factory() as client:
            return tools.get_patient_profile(client, patient_id)

    @mcp.tool
    def list_appointments(patient_id: str) -> list[dict[str, Any]]:
        """List a patient's appointments (de-identified)."""
        with client_factory() as client:
            return tools.list_appointments(client, patient_id)

    @mcp.tool
    def list_medications(patient_id: str) -> list[dict[str, Any]]:
        """List a patient's medication requests (de-identified)."""
        with client_factory() as client:
            return tools.list_medications(client, patient_id)

    @mcp.tool
    def list_care_tasks(patient_id: str) -> list[dict[str, Any]]:
        """List a patient's open care tasks (de-identified)."""
        with client_factory() as client:
            return tools.list_care_tasks(client, patient_id)

    @mcp.tool
    def get_clinical_summary(patient_id: str) -> dict[str, Any]:
        """Read profile, appointments, medications and tasks in one call."""
        with client_factory() as client:
            return tools.get_clinical_summary(client, patient_id)

    return mcp


def fhir_client_factory(settings: Settings) -> ClientFactory:
    """The production factory: a real, scoped, read-only FHIR client per call."""

    def factory() -> ManagedClient:
        return FhirClient(settings.fhir_base_url, settings.fhir_token)

    return factory


def auth_for(settings: Settings) -> StaticTokenVerifier | None:
    """Bearer auth for the MCP hop, when a token is configured.

    A shared secret is slice-grade: it keeps the tool server off the open
    internet, nothing more. Real per-caller identity is the deploy's job — see
    ``docs/API-NOTES.md``.
    """
    if not settings.mcp_auth_token:
        return None
    return StaticTokenVerifier(
        tokens={
            settings.mcp_auth_token: {
                "client_id": "care-task-agent",
                "scopes": [AUTH_SCOPE],
            }
        },
        required_scopes=[AUTH_SCOPE],
    )


def main() -> None:
    settings = Settings.from_env()
    build_server(fhir_client_factory(settings), auth=auth_for(settings)).run(
        transport="http",
        host=settings.mcp_host,
        port=settings.mcp_port,
    )


if __name__ == "__main__":
    main()
