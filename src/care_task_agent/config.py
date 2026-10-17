"""Configuration, from the environment only — nothing secret is committed."""

from __future__ import annotations

import os
from dataclasses import dataclass

# A public, unauthenticated FHIR R4 test server. Fine to default to; not production.
DEFAULT_FHIR_BASE = "https://hapi.fhir.org/baseR4"

# Where the tool server listens locally, and the path FastMCP serves MCP on.
DEFAULT_MCP_HOST = "127.0.0.1"
DEFAULT_MCP_PORT = 8765
MCP_PATH = "/mcp"


@dataclass(frozen=True)
class Settings:
    """Runtime settings. Every field is overridable from the environment."""

    fhir_base_url: str = DEFAULT_FHIR_BASE
    fhir_token: str | None = None
    google_cloud_project: str | None = None
    google_cloud_region: str = "us-central1"
    model_id: str = "gemini-2.5-flash"
    port: int = 8080

    # The tool server. `mcp_host`/`mcp_port` are where this process *listens*;
    # `mcp_server_url` is where it *reaches* the tool server (a different Cloud Run
    # service in the deploy, so it is set explicitly there).
    mcp_host: str = DEFAULT_MCP_HOST
    mcp_port: int = DEFAULT_MCP_PORT
    mcp_server_url: str | None = None
    # On Cloud Run the tool server is private and Cloud Run IAM does the
    # authenticating, so the agent proves who it is with an ID token whose audience
    # is the tool server's URL. `mcp_auth_token` is the alternative for hosting the
    # tool server somewhere that has no IAM in front of it.
    mcp_audience: str | None = None
    mcp_auth_token: str | None = None

    @property
    def mcp_url(self) -> str:
        """The tool server URL the agent connects to. An explicit URL wins."""
        if self.mcp_server_url:
            return self.mcp_server_url
        return f"http://{self.mcp_host}:{self.mcp_port}{MCP_PATH}"

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            fhir_base_url=os.environ.get("FHIR_BASE_URL", DEFAULT_FHIR_BASE),
            fhir_token=os.environ.get("FHIR_TOKEN") or None,
            google_cloud_project=os.environ.get("GOOGLE_CLOUD_PROJECT") or None,
            google_cloud_region=os.environ.get("GOOGLE_CLOUD_REGION", "us-central1"),
            model_id=os.environ.get("MODEL_ID", "gemini-2.5-flash"),
            port=int(os.environ.get("PORT", "8080")),
            mcp_host=os.environ.get("MCP_HOST", DEFAULT_MCP_HOST),
            mcp_port=int(os.environ.get("MCP_PORT", str(DEFAULT_MCP_PORT))),
            mcp_server_url=os.environ.get("MCP_SERVER_URL") or None,
            mcp_audience=os.environ.get("MCP_AUDIENCE") or None,
            mcp_auth_token=os.environ.get("MCP_AUTH_TOKEN") or None,
        )
