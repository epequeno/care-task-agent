# Cloud Run image for both halves of the deploy: the tool server and the API run this
# same image with different commands (see `just up`).
#
# Build context is the repo root. Only the `runtime` extra ships — the offline core
# (tests, offline eval) is never in the container.
FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
COPY src/ ./src/

# The lock is committed, so the image resolves nothing at build time.
RUN pip install --no-cache-dir uv && uv sync --frozen --no-dev --extra runtime

ENV PATH="/app/.venv/bin:$PATH" \
    PORT=8080
EXPOSE 8080

# The API. The tool server overrides this with `--command`/`--args`.
CMD ["python", "-m", "care_task_agent.service.app"]
