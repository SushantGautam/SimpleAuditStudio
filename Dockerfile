FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DJANGO_SETTINGS_MODULE=config.settings

WORKDIR /app

# git is required to install the SimpleAudit engine from its pinned git ref
# (declared in requirements.txt); curl is used by the healthcheck.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# Installs the platform deps AND the SimpleAudit engine (a normal pip dependency
# pinned to a git ref in requirements.txt). Provenance (version + commit) is read
# from the installed package metadata at runtime — no manual pinning here.
RUN pip install -r requirements.txt

COPY . .

# Collect static files (SPA assets, admin) so Django can serve them in
# production mode without DEBUG.
RUN python manage.py collectstatic --noinput

RUN useradd --create-home appuser \
    && mkdir -p /app/staticfiles /app/media \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/healthz || exit 1

CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2"]
