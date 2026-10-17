"""The deployed service: a thin FastAPI wrapper the Cloud Run container runs.

Needs the ``runtime`` extra. The agent is built once at start-up (which opens no
connection and calls no model) and shared across requests; each request gets its own
session. ``/task`` answers one care-team question and returns the reads it took, so
the caller can see the trajectory rather than trust the prose.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from care_task_agent.agent.agent import build_agent_from_settings
from care_task_agent.agent.runner import run_task
from care_task_agent.config import Settings


class TaskRequest(BaseModel):
    """One question about one patient."""

    task: str = Field(min_length=1, description="the care coordinator's question")
    patient_id: str = Field(min_length=1, description="the patient to read records for")


class TaskResponse(BaseModel):
    answer: str
    tool_calls: list[dict[str, Any]]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = Settings.from_env()
    app.state.settings = settings
    app.state.agent = build_agent_from_settings(settings)
    yield


app = FastAPI(title="care-task-agent", version="0.1.0", lifespan=lifespan)


@app.get("/health")
def health(request: Request) -> dict[str, Any]:
    """Liveness probe. ``wired`` says the agent exists, not that the model answers.

    Not ``/healthz``: the Cloud Run frontend answers that path itself, so an app route
    there never sees a request. Verified on the deployed service — see
    ``docs/API-NOTES.md``, divergence 8.
    """
    settings: Settings = request.app.state.settings
    return {
        "status": "ok",
        "model": settings.model_id,
        "mcp_server": settings.mcp_url,
        "fhir_base_url": settings.fhir_base_url,
        "wired": getattr(request.app.state, "agent", None) is not None,
    }


@app.post("/task")
async def run_one(request: Request, payload: TaskRequest) -> TaskResponse:
    """Answer one care-team task."""
    agent = getattr(request.app.state, "agent", None)
    if agent is None:
        raise HTTPException(status_code=503, detail="agent not built yet")

    try:
        run = await run_task(agent, task=payload.task, patient_id=payload.patient_id)
    except Exception as exc:  # noqa: BLE001 - surfaced with its message, not swallowed
        raise HTTPException(status_code=502, detail=f"{type(exc).__name__}: {exc}") from exc

    return TaskResponse(answer=run.answer, tool_calls=run.tool_calls)


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=Settings.from_env().port)


if __name__ == "__main__":
    main()
