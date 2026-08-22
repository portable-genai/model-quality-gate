# A4 AI Quality & Model-Risk Platform : API service image.
#
# Builds the FastAPI gate service with the managed-stack extra ([gcp]) installed, so the
# deployed container talks to the Gen AI evaluation service / BigQuery / GCS / Cloud
# Logging in asia-southeast1. The image is region-agnostic at build time; residency is
# enforced at runtime via config/settings.yaml (region pinned) and the deploy environment.

# --------------------------------------------------------------------------- #
# Builder : install dependencies into a venv we can copy into a slim runtime.
# --------------------------------------------------------------------------- #
FROM python:3.12-slim@sha256:423ed6ab25b1921a477529254bfeeabf5855151dc2c3141699a1bfc852199fbf AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential git \
 && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy only what the build needs first, for better layer caching. Locked, reproducible
# install: the committed lockfile pins every transitive dep; install the package itself
# with --no-deps so the lock stays authoritative (matches CI and pip-audit).
COPY pyproject.toml README.md ./
COPY requirements-gcp.lock ./
COPY src ./src
COPY config ./config

# Install the managed-stack dependencies from the lockfile, then the package with no deps.
RUN pip install -r requirements-gcp.lock && pip install --no-deps .

# --------------------------------------------------------------------------- #
# Runtime : slim, non-root, venv copied from builder.
# --------------------------------------------------------------------------- #
FROM python:3.12-slim@sha256:423ed6ab25b1921a477529254bfeeabf5855151dc2c3141699a1bfc852199fbf AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    AI_QUALITY_PROFILE=gcp \
    AI_QUALITY_SETTINGS=/app/config/settings.yaml \
    PORT=8084

WORKDIR /app

RUN useradd --create-home --uid 10001 appuser

COPY --from=builder /opt/venv /opt/venv
COPY src ./src
COPY config ./config
COPY eval ./eval

USER appuser
EXPOSE 8084

# The API exposes /healthz for liveness/readiness.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,os; urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8084')+'/healthz')" || exit 1

# Use the shell form so $PORT is expanded at container start.
CMD exec uvicorn model_quality_gate.api.app:app --host 0.0.0.0 --port ${PORT}
