# care-task-agent

A care coordinator asks a question in plain language; an agent answers it by reading
FHIR records it can only reach through a scoped, read-only tool server. The deploy is
required by the product — it is a service, not a notebook — and the model is load-bearing:
it chooses which records to read to answer the task.

**All four targets are measured**: 20/20 live task completions across four runs with 0 direct
identifiers in any prompt, 5/5 offline, 7.19 s cold start, and $1.25 per 1,000 tasks. Two private
Cloud Run services are deployed. See [`RESULTS.md`](RESULTS.md).

```
task text ──▶ ADK agent (Gemini on Vertex)
                   │  picks tools; the model decides what to read
                   ▼
             FastMCP server  ──▶  FHIR R4 read client (scoped token)
                   │                     │
                   │                     ▼
                   │            redact → projections
                   ▼            (no key and no prose carries a direct identifier)
             tool results  ──▶ agent ──▶ grounded answer
```

Deployed, that is two Cloud Run services from one image: the tool server holds the FHIR
token and the API holds the model. Neither can do the other's job. Both are **private** —
this project's org policy allows IAM grants only to its own domain, so the API proves who
it is to the tool server with a Cloud Run ID token, and the runtime service account carries
exactly two roles: `aiplatform.user`, and `run.invoker` on the tool server alone.

## Layout

| path | what it is |
|---|---|
| `src/care_task_agent/fhir/` | FHIR read client (`client.py`, `scope`), de-identification (`redact.py`), small projections (`models.py`), `smoke.py` |
| `src/care_task_agent/mcp_server/` | the read-only tools (`tools.py`) and the FastMCP server that exposes them (`server.py`) |
| `src/care_task_agent/agent/` | the ADK agent (`agent.py`), its instructions (`prompts.py`), and the task runner that records the trajectory (`runner.py`) |
| `src/care_task_agent/service/` | the FastAPI wrapper the Cloud Run container runs (`app.py`) |
| `src/care_task_agent/evals/` | the task set and the eval runner (`--offline`, and the live run) |
| `tests/`, `fixtures/` | offline tests and a synthetic FHIR bundle; `tests/runtime/` needs the `runtime` extra |

## Run it

```bash
just verify          # lint + tests + the offline eval — no model, no network
just eval-offline    # just the offline number
just test-runtime    # the MCP surface and the ADK seam — no model, no network
```

The offline half runs against `fixtures/bundle_p1.json` and a scripted policy. It exercises
the real **tool → redact → projection** path deterministically; it does **not** measure model
quality. `just test-runtime` starts a real tool server on a loopback port and drives a real
ADK toolset through it, with a scripted model.

The live half needs the `runtime` extra, a running tool server and Vertex credentials.
On a machine that has never run this: `scripts/gcp-setup.sh` walks the gcloud sign-in, the
project and billing, the four APIs, and writes every value it captures to `.env` (which the
recipes load). Then:

```bash
just mcp                       # terminal 1: the tool server, on 127.0.0.1:8765
just demo                      # terminal 2: one question, printed with its reads
just eval                      # terminal 2: the whole task set
just serve                     # the API, locally — the same app the container runs
```

`just up` deploys both services: it builds the image locally with `docker build
--platform linux/amd64` (Cloud Run refuses an Apple Silicon build; it builds locally rather
than via Cloud Build — see `docs/API-NOTES.md`), pushes to Artifact Registry, and creates the
runtime service account and its two role bindings. Because both services are private, call the
deployed API with an identity token:

```bash
gcloud auth print-identity-token | xargs -I{} curl -H "Authorization: Bearer {}" \
  https://care-task-agent-….run.app/health
```

`just down` deletes both services and says what it left behind.

## The seam, named

Synthetic patients only (a committed fixture bundle, and public FHIR sandboxes for the live
half). **No PHI, no BAA, read-only access.** This artifact shows the mechanism — scoped reads,
de-identification, audit-shaped tool calls — against the real standard. It does not show
operating under an audit.

Two things the fixture would never have produced, both pinned by tests. The scope is
deliberately narrow — four resource types — and the client refuses anything else *before* a
request goes out. And the patient's own identifier strings are scrubbed from free text: a real
`Task` from a public sandbox read *"Review appointment request from Babara Rice"*, and
`redact()`, which strips keys, does not touch prose.

## Measurement

- **number:** offline — 5/5 tasks, 0 direct identifiers leaked, unknown patient refused, 0 out-of-scope resources (`just verify`, 2026-10-17). live — 4 consecutive runs, 5/5 each: 20/20 task completions, 0 direct identifiers in any prompt (`just mcp` + `just eval`, 2026-10-17, `gemini-2.5-flash` on Vertex). deployed — cold start 7.19 s, warm 0.078 s, warm task 9.34 s, $1.25 per 1,000 tasks (`just up`, same date; the cost is derived from measured tokens and published prices, not from an invoice)
- **command:** `just verify` (offline) · `just eval` (live) · `just up` (deploy)
- **date:** 2026-10-17
