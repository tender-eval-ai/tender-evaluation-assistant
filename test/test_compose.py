"""docker-compose.yml runs the whole stack: Postgres, the API, the worker on the same
image, the UI; the synthetic case is mounted in the inbox; the worker drains on stop."""
from pathlib import Path

import yaml

COMPOSE = yaml.safe_load((Path(__file__).resolve().parents[1] / "docker-compose.yml").read_text())
SERVICES = COMPOSE["services"]


def test_the_four_services_and_the_database_volume():
    assert set(SERVICES) == {"postgres", "backend", "worker", "frontend"} and "pgdata" in COMPOSE["volumes"]
    assert SERVICES["postgres"]["image"].startswith("postgres:16") and "healthcheck" in SERVICES["postgres"]


def test_api_and_worker_share_the_image_the_database_and_the_data_volume():
    api, worker = SERVICES["backend"], SERVICES["worker"]
    assert api["build"] == worker["build"] == {"context": ".", "dockerfile": "backend/Dockerfile"}
    for svc in (api, worker):
        env = dict(e.split("=", 1) for e in svc["environment"])
        assert env["DATABASE_URL"].startswith("postgresql://postgres:") and "@postgres:5432/tender" in env["DATABASE_URL"]
        assert env["DATA_DIR"] == "/data" and "./data:/data" in svc["volumes"]
        assert svc["depends_on"]["postgres"]["condition"] == "service_healthy"
    assert worker["command"] == ["python", "-m", "app.jobs.worker", "--pipelines", "app.checks.vendor_check", "app.rulesets.build_job"]
    assert worker["stop_grace_period"] == "60s", "SIGTERM must have time to drain the running jobs"


def test_the_synthetic_case_is_importable_from_the_inbox():
    assert "./test/data/synthetic_tender:/inbox/synthetic_tender:ro" in SERVICES["backend"]["volumes"]
    assert (Path(__file__).resolve().parents[1] / "backend" / "Dockerfile").read_text().count("COPY migrations migrations") == 1
