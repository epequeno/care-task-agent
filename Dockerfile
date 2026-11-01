# Cloud Run image for both halves of the deploy: the tool server and the API run this
# same image with different commands (see `just up`).
#
# Build context is the repo root. Only the `runtime` extra ships — the offline core
# (tests, offline eval) is never in the container.
FROM python:3.12-slim

WORKDIR /app

# eMudhra/emSign intermediate CA incident (2026-10-20): pip trusts the
# compromised intermediates through its vendored CA bundle regardless of the
# system store, so replace it from a hash-pinned wheel before installing
# anything. Needs pip >= 26.2.2.
RUN python -m pip install --no-cache-dir --no-deps \
    "pip @ https://files.pythonhosted.org/packages/3f/06/3e4420302363fbb71be3c7f35ce042f54bfca330e3e66b3a2e3c4cca579f/pip-26.2.2-py3-none-any.whl#sha256=fd7f4dfa8190e014013b9f08f3e973f4e4c26ffd179a204895533a7254813a70"

COPY pyproject.toml uv.lock README.md ./
COPY src/ ./src/

# The lock is committed, so the image resolves nothing at build time.
RUN pip install --no-cache-dir uv && uv sync --frozen --no-dev --extra runtime

ENV PATH="/app/.venv/bin:$PATH" \
    PORT=8080
EXPOSE 8080

# The API. The tool server overrides this with `--command`/`--args`.
CMD ["python", "-m", "care_task_agent.service.app"]
