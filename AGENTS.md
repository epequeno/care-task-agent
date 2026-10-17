# care-task-agent — notes for an agent working here

A thin vertical slice: an ADK agent reading FHIR records through a FastMCP tool server, on
Cloud Run, synthetic patients only. Read `README.md` for the shape and `RESULTS.md` for the gate.

## Conventions

- **`just`, not `make`.** Recipes for unbuilt stages `exit 1` rather than being omitted, so a
  broken stage is loud.
- In recipe bodies use a single `$` — `$$` reaches bash as the PID and fails silently.
- The offline half must stay **dependency-light and hermetic**: `just verify` runs with no model,
  no network, no cloud credentials. Add heavy deps to the `runtime` extra, never the base.
- `fhir/redact.py` is the safety-critical module: **nothing reaches the model without passing
  through it.** Any new tool must redact before returning.
- Record verified-vs-assumed cloud/SDK facts in `docs/API-NOTES.md` before building on them.
- Do not claim a number that was not measured. `RESULTS.md` is the only place numbers live.

## Scope

The stack this slice exercises: GCP (Cloud Run, Artifact Registry, Vertex), Google ADK, a
FastMCP tool server, and read-only FHIR. Azure-only services, App Insights/Kusto and Semantic
Kernel are out of scope. The FHIR credential is server-side, so this is **not** delegated
authorization — see `docs/API-NOTES.md`.
