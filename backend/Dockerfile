# Backend and worker image — build from the repo root:
#   docker build -f backend/Dockerfile -t tea-backend .
# The worker is the same image with: python -m app.jobs.worker --pipelines app.checks.vendor_check
# It installs exactly backend/requirements.lock (hashed; the root lock's versions without the
# test and MCP packages) and runs as the unprivileged user `app`, uid 1000. On a Linux host,
# a bind-mounted ./data must be writable by uid 1000 (README, "Service mode").
FROM python:3.12-slim

WORKDIR /srv
COPY backend/requirements.lock backend/requirements.lock
RUN pip install --no-cache-dir --require-hashes -r backend/requirements.lock

COPY app app
COPY backend backend
COPY migrations migrations

# Before VOLUME, so a volume Docker creates for /data starts out owned by `app`.
RUN useradd --uid 1000 --create-home --shell /usr/sbin/nologin app && mkdir -p /data && chown app:app /data
USER app
ENV DATA_DIR=/data
VOLUME /data
EXPOSE 8000

CMD ["uvicorn", "backend.api:app", "--host", "0.0.0.0", "--port", "8000"]
