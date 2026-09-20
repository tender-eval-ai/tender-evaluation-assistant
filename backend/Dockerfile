# Backend and worker image — build from the repo root:
#   docker build -f backend/Dockerfile -t tea-backend .
# The worker is the same image with: python -m app.jobs.worker --pipelines app.checks.vendor_check
FROM python:3.12-slim

WORKDIR /srv
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY app app
COPY backend backend
COPY migrations migrations

ENV DATA_DIR=/data
VOLUME /data
EXPOSE 8000

CMD ["uvicorn", "backend.api:app", "--host", "0.0.0.0", "--port", "8000"]
