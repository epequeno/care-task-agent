# API notes — what is verified, and what is still an assumption

**Status: verified for the whole offline half and the whole MCP/agent seam.** Every row
under *Verified* was read from the installed package or measured against a live server
on the date shown — not from documentation, not from memory. The *Assumed* rows are the
ones that still need a cloud or an account this checkout does not have; nothing is built
on them that has not been labelled.

## Verified — SDK surfaces (read from the installed packages, 2026-10-17)

| Fact | Value | Source |
|---|---|---|
| `google-adk` current at **2.x** | 2.12.0, requires Python >=3.11 | PyPI JSON, 2026-10-17 |
| `fastmcp` current version | 4.1.0, requires Python >=3.10 | PyPI JSON, 2026-10-17 |
| `google-genai` current version | 2.31.0 | PyPI JSON, 2026-10-17 |
| ADK's MCP client surface | `McpToolset(connection_params=StreamableHTTPConnectionParams(url=…, headers=…))`. `MCPToolset` is a **deprecated alias** | `google/adk/tools/mcp_tool/mcp_toolset.py:148`, `mcp_session_manager.py:504` |
| ADK's model construction for Vertex | `Gemini(model=…, client_kwargs={"enterprise": True, "project":…, "location":…})`; `client_kwargs` is a declared field | `google/adk/models/google_llm.py:141,455` |
| Vertex backend flag | `GOOGLE_GENAI_USE_ENTERPRISE`; `GOOGLE_GENAI_USE_VERTEXAI` warns as deprecated. Values `true`/`1` | `google/adk/utils/_gcp_metadata.py:31`, `google/genai/_api_client.py:707` |
| `fastmcp` server | `FastMCP(name, auth=…)`; bare `@mcp.tool`; `run(transport="http", host=…, port=…)`; default path `/mcp` | `fastmcp/server/server.py:320`, `mixins/transport.py:107,253`, `settings.py:196-203` |
| `fastmcp` bearer auth | `StaticTokenVerifier(tokens={token: {client_id, scopes}}, required_scopes=[…])` — its own docstring says development only | `fastmcp/server/auth/providers/jwt.py:684` |
| ADK runner | `Runner(app_name=…, agent=…, session_service=…)`, `InMemoryRunner`, `session_service.create_session(app_name=…, user_id=…)` | `google/adk/runners.py:275,2378`, `sessions/base_session_service.py:70` |
| ADK event/callback surface | `Event` **is** an `LlmResponse` (`event.get_function_calls()`); `before_model_callback(ctx, LlmRequest)` | `google/adk/events/event.py:87`, `models/llm_response.py:196`, `agents/llm_agent.py:92` |

## Verified — live behaviour (measured over the network, 2026-10-17)

| Fact | Evidence |
|---|---|
| SMART Health IT sandbox is live | HTTP 200; `Smile CDR`, `fhirVersion 4.0.0` — `launch.smarthealthit.org/v/r4/fhir/metadata` |
| Every gcloud command the deploy and the setup wizard use exists in SDK **589.0.0** | `gcloud run deploy` (`--image`, `--region`, `--command`, `--args`, `--set-env-vars`, `--allow-unauthenticated`), `gcloud builds submit`, `gcloud artifacts repositories create/describe --repository-format docker`, `gcloud services enable`, `gcloud billing projects describe`, `gcloud auth login`, `gcloud auth application-default login` / `set-quota-project` — each `--help` read locally, 2026-10-17 |
| The Vertex endpoint path is right | `POST https://us-central1-aiplatform.googleapis.com/v1/projects/<p>/locations/us-central1/publishers/google/models/gemini-2.5-flash:generateContent` returned a structured API error (`SERVICE_DISABLED`, then `BILLING_DISABLED`) before billing was linked, never a routing 404 — so the publisher/model path resolves |
| Vertex AI is **off by default** on a new project | `aiplatform.googleapis.com` had to be enabled on `your-project` before the endpoint stopped answering `SERVICE_DISABLED` |
| `gemini-2.5-flash` exists on Vertex in `us-central1` | `google.genai.Client(enterprise=True, project=…, location='us-central1').models.generate_content(model='gemini-2.5-flash', …)` returned text; and the live eval ran 4×5 tasks on it |
| A billing account must be *linked* to the project, not merely created | after creating one, `billingAccountName` was still `""` and Vertex kept answering `BILLING_DISABLED` until `gcloud billing projects link` |
| Epic on FHIR sandbox is live | HTTP 200 — `fhir.epic.com` |
| HAPI public FHIR R4 is live | HTTP 200, returns a Bundle — `hapi.fhir.org/baseR4/Patient?_count=1` |
| The search parameters the tools use are accepted | `Appointment?patient=Patient/<id>`, `MedicationRequest?patient=<id>`, `Task?patient=<id>` all returned Bundles from the SMART sandbox — `just fhir-smoke`, and `get_clinical_summary` over MCP |
| The agent reaches the tool server over MCP | `just test-runtime` drives a real `McpToolset` against a real FastMCP server on a loopback port |
| An unauthenticated caller is refused | with `MCP_AUTH_TOKEN` set: no token and a wrong token both fail to open a session; the right token lists all five tools |
| FastMCP returns a tool result in **two** shapes | a structure under `structuredContent`, or the same JSON as a string in `content[0].text`. Both reach the model; the eval walks both |
| The container image runs | `docker build` then `/health` from the running image; `python -m care_task_agent.mcp_server.server` imports in the same image |
| The deployed API answers a real task | `POST /task` on the Cloud Run service returned 200 with a grounded answer and its tool-call trajectory — identity token → API → ID token → private tool server → FHIR → Vertex |
| Both deployed services refuse unauthenticated callers | `403` from the tool server's `/mcp` without a token |
| The deploy shape in `just up` works | two private Cloud Run services from one image, the runtime service account created with two role bindings, `--command python --args=-m,care_task_agent.mcp_server.server` for the tool server; Artifact Registry repository and image path as written |
| Cloud Run timing, measured on the deployed API | cold start **7.19 s** (first request to a fresh revision), warm **0.078 s**, warm `POST /task` **9.34 s** end to end |

## Divergences found so far

The point of this file. Each of these would have been a wrong claim if written from
documentation:

1. **FHIR free text carries the patient's name, and key-stripping does not remove it.**
   A real `Task` from the SMART sandbox read
   `"description": "Review appointment request from Babara Rice"`. `redact()` removes
   *keys*; a name inside prose survives it, and the model read the name. Fixed by
   `redact.direct_identifier_strings` + `redact.scrub_free_text`, applied to every
   free-text field a projection returns. `tests/test_tools.py` pins the case.
2. **The MCP tool name changed.** The widely-posted `MCPToolset` is deprecated in ADK
   2.12; the current name is `McpToolset`.
3. **The Vertex flag was renamed.** `GOOGLE_GENAI_USE_VERTEXAI` now emits a
   deprecation warning; `GOOGLE_GENAI_USE_ENTERPRISE` is the current name.
4. **The target was "FastMCP v3"; PyPI's current release is 4.1.0**, and the
   4.x server/tool decorator surface is what this repo is written against.
5. **`gcloud builds submit` had no Cloud Build service account to run as.** At first use,
   the project's Cloud Build service account (`<project-number>@cloudbuild.gserviceaccount.com`) did not exist — only the Compute default
   service account, which itself carries no roles — and the command failed with
   `PERMISSION_DENIED: The caller does not have permission`. `just up` was changed to build
   locally with `docker build` and push to Artifact Registry. **The account did appear
   later**, with `roles/cloudbuild.builds.builder`, once the API had been enabled a second
   time — so the local build is now a choice rather than a necessity, and it remains the
   path that has actually been run.
6. **The org policy forbids public Cloud Run services.** `constraints/iam.allowedPolicyMemberDomains`
   allows only domain `<org-domain-id>`, so `--allow-unauthenticated` fails on
   `Setting IAM policy`. Both services are therefore private, and the agent authenticates
   to the tool server with a Cloud Run **ID token** (`MCP_AUDIENCE` → `header_provider`),
   not with the shared secret. The shared secret stays in the code for hosting outside
   Cloud Run, where there is no IAM to lean on.
7. **An Apple Silicon `docker build` produces `linux/arm64`, which Cloud Run refuses** —
   `Container manifest type 'application/vnd.oci.image.index.v1+json' must support
   amd64/linux`. The recipe builds with `--platform linux/amd64`.
8. **Cloud Run reserves `/healthz`.** The deployed app advertises `/healthz` in its own
   OpenAPI schema and answers `/healthz/` with a 307 — but a request to exactly `/healthz`
   is answered by Google's frontend with its own HTML 404 and never reaches the container.
   No other path behaves this way (`/health`, `/livez`, `/readyz`, `/healthz2`, `/_healthz`
   all reach the app). The health endpoint is therefore `/health`. Found only because the
   service was deployed; nothing local can show it.
9. **`gcloud auth application-default login` crashes on a reduced consent.** Google
   returned `userinfo.email openid` for a request that asked for four scopes, and
   gcloud died with `ERROR: gcloud crashed (Warning): Scope has changed from … to …`.
   The raise is oauthlib's RFC 6749 §3.3 check, bundled at
   `lib/third_party/oauthlib/oauth2/rfc6749/parameters.py:455` — gcloud does not catch
   it. It is not a policy block: the same client and account granted `cloud-platform`
   through `gcloud auth login` minutes earlier (checked with `oauth2.googleapis.com/tokeninfo`).
   Grant every scope on the consent screen, and check which account it names.

## Assumed — verify before building on

| Assumption | Where it bites | How to check |
|---|---|---|
| SMART-on-FHIR launch (a per-user delegated token) | `fhir/client.py` live path | SMART app launch spec. **Not built**: the FHIR token is a server-side credential, so this slice is not delegated authorization |
| The fixture bundle is representative of sandbox data | `fixtures/bundle_p1.json` | it is hand-written; the free-text divergence above is what real sandbox data looks like |
| The cost per 1,000 tasks is derived, not invoiced | `RESULTS.md` | it is measured tokens × published prices; a billing export would be the real answer |
| The cold-start figure is a fresh revision, not a post-idle scale-from-zero start | `RESULTS.md` | five minutes after the last request the instance was still warm, so the idle case was never observed |
