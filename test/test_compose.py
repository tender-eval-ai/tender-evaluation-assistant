"""docker-compose.yml runs the whole stack: Postgres, the API, the worker on the same
image, the UI; the synthetic case is mounted in the inbox; the worker drains on stop."""
from fnmatch import fnmatch
from pathlib import Path

import yaml

COMPOSE = yaml.safe_load((Path(__file__).resolve().parents[1] / "docker-compose.yml").read_text())
SERVICES = COMPOSE["services"]


def test_the_four_services_and_the_database_volume():
    assert set(SERVICES) == {"postgres", "backend", "worker", "web"} and "pgdata" in COMPOSE["volumes"]
    assert SERVICES["postgres"]["image"].startswith("postgres:16") and "healthcheck" in SERVICES["postgres"]


def test_api_and_worker_share_the_image_the_database_and_the_data_volume():
    api, worker = SERVICES["backend"], SERVICES["worker"]
    assert api["build"] == worker["build"] == {"context": ".", "dockerfile": "backend/Dockerfile"}
    for svc in (api, worker):
        env = dict(e.split("=", 1) for e in svc["environment"])
        assert env["DATABASE_URL"].startswith("postgresql://postgres:") and "@postgres:5432/tender" in env["DATABASE_URL"]
        assert env["DATA_DIR"] == "/data" and "./data:/data" in svc["volumes"]
        assert svc["depends_on"]["postgres"]["condition"] == "service_healthy"
    assert worker["command"] == ["python", "-m", "app.jobs.worker", "--pipelines", "app.checks.vendor_check,app.rulesets.build_job,app.jobs.evaluate_job"]
    assert worker["stop_grace_period"] == "60s", "SIGTERM must have time to drain the running jobs"


def test_the_synthetic_case_is_importable_from_the_inbox():
    assert "./test/data/synthetic_tender:/inbox/synthetic_tender:ro" in SERVICES["backend"]["volumes"]
    assert (Path(__file__).resolve().parents[1] / "backend" / "Dockerfile").read_text().count("COPY migrations migrations") == 1


def test_the_ui_adds_the_api_key_on_the_server():
    """The React app is built against the real API on its own origin; nginx forwards the
    API's paths and sets X-API-Key from the environment, so no key is in the bundle."""
    web = SERVICES["web"]
    env = dict(e.split("=", 1) for e in web["environment"])
    assert web["build"] == {"context": "./web"} and env["BACKEND_URL"] == "http://backend:8000"
    assert env["API_KEY"] == "${API_KEY:-}"
    root = Path(__file__).resolve().parents[1] / "web"
    assert "ENV VITE_API_MOCK=0" in (root / "Dockerfile").read_text()
    conf = (root / "docker" / "default.conf.template").read_text()
    assert 'proxy_set_header X-API-Key "${API_KEY}";' in conf and "proxy_pass ${BACKEND_URL};" in conf


def test_the_template_library_is_built_into_the_image():
    """app/rulesets/templates/ reaches the image: the Dockerfile copies app/, and no
    .dockerignore pattern matches the folder, its files or a parent. (J11-1: before, the
    compose stack had no library, so every item was drafted as novel.)"""
    root = Path(__file__).resolve().parents[1]
    assert "COPY app app" in (root / "backend" / "Dockerfile").read_text()
    patterns = [p.strip().rstrip("/") for p in (root / ".dockerignore").read_text().splitlines()
                if p.strip() and not p.startswith("#")]
    path = "app/rulesets/templates/price_schedule.json"
    prefixes = ["/".join(path.split("/")[:n]) for n in range(1, path.count("/") + 2)]
    excluded = [(p, pre) for p in patterns for pre in prefixes if fnmatch(pre, p) or fnmatch(pre, f"**/{p}")]
    assert not excluded, f".dockerignore keeps templates out of the image: {excluded}"
    assert (root / "app" / "rulesets" / "templates").is_dir()
