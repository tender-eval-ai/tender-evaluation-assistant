"""The backend image (J11-3): the hashed lock at the versions CI tests, an unprivileged user
the Azure share is mounted as, and health checks for the API and the worker in compose."""
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SERVICES = yaml.safe_load((ROOT / "docker-compose.yml").read_text())["services"]


def pins(path: str) -> dict[str, str]:
    return dict(re.findall(r"^([A-Za-z0-9_.-]+)(?:\[[^\]]*\])?==([^ \\\n;]+)", (ROOT / path).read_text(), re.M))


def test_the_image_installs_the_hashed_lock_and_runs_unprivileged():
    dockerfile = (ROOT / "backend" / "Dockerfile").read_text()
    assert "pip install --no-cache-dir --require-hashes -r backend/requirements.lock" in dockerfile
    assert "useradd --uid 1000" in dockerfile and "\nUSER app\n" in dockerfile
    assert dockerfile.index("chown app:app /data") < dockerfile.index("VOLUME /data"), "a new volume starts out owned by app"
    assert "mountOptions: 'uid=1000,gid=1000'" in (ROOT / "deploy" / "azure" / "main.bicep").read_text()


def test_the_image_ships_the_versions_ci_tests():
    shipped, tested = pins("backend/requirements.lock"), pins("requirements.lock")
    assert len(shipped) > 50 and "--hash=sha256:" in (ROOT / "backend" / "requirements.lock").read_text()
    assert {k: (v, tested.get(k)) for k, v in shipped.items() if tested.get(k) != v} == {}, \
        "recompile backend/requirements.lock with -c requirements.lock"
    assert "pytest" not in shipped and "mcp" not in shipped, "test and MCP packages stay out of the image"


def test_the_api_and_the_worker_report_their_health_and_the_ui_waits_for_the_api():
    api, worker, web = SERVICES["backend"], SERVICES["worker"], SERVICES["web"]
    assert "http://localhost:8000/health" in " ".join(api["healthcheck"]["test"])
    assert worker["healthcheck"]["test"] == ["CMD", "python", "-m", "app.jobs.health"]
    assert web["depends_on"]["backend"]["condition"] == "service_healthy"
