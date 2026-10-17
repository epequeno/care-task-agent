# care-task-agent — an ADK agent whose FHIR tools live behind a FastMCP server.
#
# Two halves, two toolchains:
#   just verify   the offline half — lint, tests, and the offline eval. No model, no cloud.
#   just eval     the live half — needs the `runtime` extra, a running tool server, Vertex.
# Unbuilt stages exit non-zero rather than being quietly omitted.
set shell := ["bash", "-uc"]

# Recipes read `.env` when it exists — see `.env.example`. Nothing is exported back to
# the calling shell, so `just` and a bare `python -m …` do not disagree by accident.
set dotenv-load := true

default:
    @just --list

# Fail loudly if uv is missing, rather than failing confusingly in a later recipe.
# The version goes to stderr: recipes like `eval` put machine-readable output on stdout,
# and a banner in front of it breaks anything piping into jq.
toolchain:
    @command -v uv >/dev/null || { echo "uv not installed — see https://docs.astral.sh/uv/"; exit 1; }
    @uv --version >&2

sync: toolchain
    @uv sync --quiet

sync-runtime: toolchain
    @uv sync --extra runtime --quiet

lint: sync
    @uv run ruff check .
    @uv run ruff format --check .

fmt: sync
    @uv run ruff format .
    @uv run ruff check --fix .

test: sync
    @uv run pytest

# Tests for the runtime half (the MCP tool surface). Kept out of `just test` so the
# offline half stays installable with the base dependencies alone.
test-runtime: sync-runtime
    @uv run --extra runtime pytest tests/runtime

# The gate for the offline half: lint, tests, and a number from the offline eval.
verify: lint test eval-offline

# Offline eval: fixture bundle + scripted policy. Deterministic, no model, no network.
# Exercises the real tool -> redact -> projection path; it does NOT measure model quality.
eval-offline: sync
    @uv run python -m care_task_agent.evals.run --offline

# Live eval: the real agent, a real FHIR server, a real model. Needs `just mcp`
# running in another shell and Vertex credentials.
eval: sync-runtime
    @uv run python -m care_task_agent.evals.run

# --- the two halves of the deploy, locally --------------------------------------

# The tool server. Long-running; the agent reaches it at MCP_SERVER_URL
# (default http://127.0.0.1:8765/mcp).
mcp: sync-runtime
    @uv run python -m care_task_agent.mcp_server.server

# One real read from FHIR_BASE_URL through the real tools. No model, no MCP hop.
# Point it at a sandbox first:
#   FHIR_BASE_URL=https://launch.smarthealthit.org/v/r4/fhir just fhir-smoke
fhir-smoke: sync
    @uv run python -m care_task_agent.fhir.smoke

# One care task through the real agent. Needs `just mcp` running and Vertex credentials.
demo *args: sync-runtime
    @uv run python -m care_task_agent.agent.runner {{args}}

# The API, locally — the same app the container runs.
serve: sync-runtime
    @uv run python -m care_task_agent.service.app

# --- deploy ---------------------------------------------------------------------
# One image, two Cloud Run services: the tool server holds the FHIR token, the API
# holds the model. Neither can do the other's job.
#
# Both are private. This project's org policy allows IAM grants only to its own domain,
# so `--allow-unauthenticated` is impossible; the API therefore proves who it is to the
# tool server with an ID token whose audience is the tool server's URL (MCP_AUDIENCE),
# and the runtime service account needs exactly two roles: aiplatform.user, and
# run.invoker on the tool server alone.
#
# The image is built here rather than by Cloud Build — Cloud Build had no service account to
# run as when this was written (see docs/API-NOTES.md) — and --platform linux/amd64 is
# required: an Apple Silicon build is arm64 and Cloud Run refuses it.
up: sync-runtime
    @set -eu; \
    command -v gcloud >/dev/null || { echo "gcloud not installed — see https://cloud.google.com/sdk/docs/install"; exit 1; }; \
    command -v docker >/dev/null || { echo "docker not installed — this recipe builds the image locally"; exit 1; }; \
    : "${GOOGLE_CLOUD_PROJECT:?set GOOGLE_CLOUD_PROJECT — scripts/gcp-setup.sh writes it to .env}"; \
    REGION="${GOOGLE_CLOUD_REGION:-us-central1}"; \
    FHIR_BASE="${FHIR_BASE_URL:-https://launch.smarthealthit.org/v/r4/fhir}"; \
    REPOSITORY=care-task-agent; \
    RUNTIME_SA="care-task-agent@$GOOGLE_CLOUD_PROJECT.iam.gserviceaccount.com"; \
    IMAGE="$REGION-docker.pkg.dev/$GOOGLE_CLOUD_PROJECT/$REPOSITORY/care-task-agent"; \
    gcloud artifacts repositories describe "$REPOSITORY" --location "$REGION" >/dev/null 2>&1 \
        || gcloud artifacts repositories create "$REPOSITORY" \
            --repository-format docker --location "$REGION"; \
    gcloud iam service-accounts describe "$RUNTIME_SA" >/dev/null 2>&1 \
        || gcloud iam service-accounts create care-task-agent \
            --display-name "care-task-agent Cloud Run runtime"; \
    gcloud projects add-iam-policy-binding "$GOOGLE_CLOUD_PROJECT" \
        --member="serviceAccount:$RUNTIME_SA" --role=roles/aiplatform.user --condition=None >/dev/null; \
    gcloud auth configure-docker "$REGION-docker.pkg.dev" --quiet >/dev/null; \
    echo "building $IMAGE for linux/amd64"; \
    docker build --platform linux/amd64 -t "$IMAGE" .; \
    docker push "$IMAGE"; \
    echo "deploying care-task-fhir (the tool server, private)"; \
    gcloud run deploy care-task-fhir --image "$IMAGE" --region "$REGION" \
        --no-allow-unauthenticated \
        --command python --args=-m,care_task_agent.mcp_server.server \
        --set-env-vars "MCP_HOST=0.0.0.0,MCP_PORT=8080,FHIR_BASE_URL=$FHIR_BASE"; \
    MCP_URL="$(gcloud run services describe care-task-fhir --region "$REGION" --format 'value(status.url)')"; \
    gcloud run services add-iam-policy-binding care-task-fhir --region "$REGION" \
        --member="serviceAccount:$RUNTIME_SA" --role=roles/run.invoker >/dev/null; \
    echo "deploying care-task-agent (the API, private) against $MCP_URL/mcp"; \
    gcloud run deploy care-task-agent --image "$IMAGE" --region "$REGION" \
        --no-allow-unauthenticated \
        --service-account "$RUNTIME_SA" \
        --set-env-vars "MCP_SERVER_URL=$MCP_URL/mcp,MCP_AUDIENCE=$MCP_URL,FHIR_BASE_URL=$FHIR_BASE,GOOGLE_CLOUD_PROJECT=$GOOGLE_CLOUD_PROJECT,GOOGLE_CLOUD_REGION=$REGION"; \
    API_URL="$(gcloud run services describe care-task-agent --region "$REGION" --format 'value(status.url)')"; \
    echo "up: $API_URL"; \
    echo "both services are private — this org forbids public ones. Call the API with an identity token:"; \
    echo "  gcloud auth print-identity-token | xargs -I{} curl -H \"Authorization: Bearer {}\" $API_URL/health"

down:
    @set -eu; \
    : "${GOOGLE_CLOUD_PROJECT:?set GOOGLE_CLOUD_PROJECT}"; \
    REGION="${GOOGLE_CLOUD_REGION:-us-central1}"; \
    gcloud run services delete care-task-agent --region "$REGION" --quiet; \
    gcloud run services delete care-task-fhir --region "$REGION" --quiet; \
    echo "left behind on purpose — the runtime service account, the Artifact Registry"; \
    echo "repository, and the image in it. Remove them with:"; \
    echo "  gcloud iam service-accounts delete care-task-agent@$GOOGLE_CLOUD_PROJECT.iam.gserviceaccount.com"; \
    echo "  gcloud artifacts repositories delete care-task-agent --location $REGION"

check: verify
