FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DJANGO_SETTINGS_MODULE=config.settings \
    # The SimpleAudit engine (Target -> Auditor -> Judge) is vendored from a
    # pinned git checkout at build time. core.engine loads it lazily from this
    # path; the web process never imports it, only the worker does.
    SIMPLEAUDIT_ENGINE_PATH=/opt/simpleaudit

# Pin the engine commit for reproducible builds. Override with
# --build-arg SIMPLEAUDIT_COMMIT=<sha> to audit against a different revision.
ARG SIMPLEAUDIT_REPO=https://github.com/kelkalot/simpleaudit.git
ARG SIMPLEAUDIT_COMMIT=843d581

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

# Vendor the SimpleAudit engine at a pinned commit so audits are reproducible
# and the image is self-contained (no sibling checkout required at runtime).
RUN git clone --quiet "$SIMPLEAUDIT_REPO" /opt/simpleaudit \
    && git -C /opt/simpleaudit checkout --quiet "$SIMPLEAUDIT_COMMIT" \
    && git -C /opt/simpleaudit rev-parse HEAD > /opt/simpleaudit/.pinned_commit

COPY . .

# Collect static files (SPA assets, admin) so Django can serve them in
# production mode without DEBUG.
RUN python manage.py collectstatic --noinput

RUN useradd --create-home appuser \
    && mkdir -p /app/staticfiles /app/media \
    && chown -R appuser:appuser /app /opt/simpleaudit
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/healthz || exit 1

CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2"]
