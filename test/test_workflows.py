"""The workflows' supply chain (J11-6): every action pinned to a full commit with its version
in a comment (Dependabot moves both), a read-only token unless a job asks for more, and the
one binary CI downloads checked against its release checksum."""
import re
from pathlib import Path

WORKFLOWS = sorted((Path(__file__).resolve().parents[1] / ".github" / "workflows").glob("*.yml"))
PINNED = re.compile(r"uses: [\w.-]+/[\w./-]+@[0-9a-f]{40}  # v\d+\.\d+\.\d+$")


def test_every_action_is_pinned_to_a_commit_with_its_version():
    assert WORKFLOWS
    for path in WORKFLOWS:
        for n, line in enumerate(path.read_text().splitlines(), 1):
            if "uses:" in line:
                assert PINNED.search(line.strip()), f"{path.name}:{n} is not pinned to a commit: {line.strip()}"


def test_the_token_is_read_only_unless_a_job_asks_for_more():
    for path in WORKFLOWS:
        assert re.search(r"^permissions:\n  contents: read$", path.read_text(), re.M), f"{path.name}: no workflow-level permissions"


def test_the_gitleaks_download_is_checked_before_it_runs():
    ci = (WORKFLOWS[0].parent / "ci.yml").read_text()
    assert re.search(r"GITLEAKS_SHA256: [0-9a-f]{64}", ci) and 'sha256sum -c -' in ci
    assert ci.index("sha256sum -c -") < ci.index("./gitleaks git"), "checked before it is run"
