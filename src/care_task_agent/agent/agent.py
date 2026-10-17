"""Build the ADK agent whose tools are discovered through the FastMCP server.

The agent never imports the tools: it connects to the tool server by URL and the
model decides which of them to call. That is the seam the whole artifact is about —
the only way to a record is a tool call the model chose to make.

The ADK surface here was read from the installed ``google-adk`` 2.12.0 before it
was written — see ``docs/API-NOTES.md``. ``McpToolset`` is the current name;
``MCPToolset`` is deprecated.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from google.adk.agents import LlmAgent
from google.adk.models import Gemini
from google.adk.tools.mcp_tool import McpToolset, StreamableHTTPConnectionParams

from care_task_agent.agent import prompts
from care_task_agent.config import Settings

APP_NAME = "care_task_agent"
AGENT_NAME = "care_task_agent"


def id_token_provider(audience: str) -> Callable[..., dict[str, str]]:
    """Headers proving to Cloud Run IAM which service is calling.

    A fresh token per MCP session, on purpose: an ID token fetched once at start-up
    would work for an hour and then quietly stop.
    """

    def provider(_context: Any) -> dict[str, str]:
        from google.auth.transport.requests import Request
        from google.oauth2 import id_token

        return {"Authorization": f"Bearer {id_token.fetch_id_token(Request(), audience)}"}

    return provider


def build_agent(
    mcp_server_url: str,
    *,
    model: str,
    project: str | None = None,
    region: str = "us-central1",
    mcp_audience: str | None = None,
    mcp_auth_token: str | None = None,
    before_model_callback: Callable[..., Any] | None = None,
) -> LlmAgent:
    """The care-task agent, reading records only through ``mcp_server_url``.

    Vertex is set on the model explicitly rather than left to the environment: the
    deploy knows its project, and a stale env var should not silently move the call
    to a different backend. ``before_model_callback`` is how the eval sees the exact
    prompt the model is sent; the service leaves it unset.

    Two ways to authenticate the MCP hop, and they are alternatives, not layers:
    ``mcp_audience`` for a tool server behind Cloud Run IAM (a private service — the
    only kind this project's org policy allows), ``mcp_auth_token`` for one that is
    merely on a network. With neither, the tool server is unauthenticated, which is
    what running it on loopback means.
    """
    if mcp_audience:
        toolset = McpToolset(
            connection_params=StreamableHTTPConnectionParams(url=mcp_server_url),
            header_provider=id_token_provider(mcp_audience),
        )
    else:
        headers = {"Authorization": f"Bearer {mcp_auth_token}"} if mcp_auth_token else None
        toolset = McpToolset(
            connection_params=StreamableHTTPConnectionParams(url=mcp_server_url, headers=headers)
        )
    client_kwargs: dict[str, Any] = {"enterprise": True, "location": region}
    if project:
        client_kwargs["project"] = project

    return LlmAgent(
        name=AGENT_NAME,
        model=Gemini(model=model, client_kwargs=client_kwargs),
        instruction=prompts.SYSTEM_INSTRUCTION,
        tools=[toolset],
        before_model_callback=before_model_callback,
    )


def build_agent_from_settings(settings: Settings, **kwargs: Any) -> LlmAgent:
    """``build_agent`` wired to ``Settings``, so callers do not repeat the mapping."""
    return build_agent(
        settings.mcp_url,
        model=settings.model_id,
        project=settings.google_cloud_project,
        region=settings.google_cloud_region,
        mcp_audience=settings.mcp_audience,
        mcp_auth_token=settings.mcp_auth_token,
        **kwargs,
    )
