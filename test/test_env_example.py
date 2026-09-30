"""Configuration (J11-4): every environment variable the service reads is documented in
.env.example, and a setting has one default in code. Found by reading the code's syntax
tree for os.environ / os.getenv / env.get / env[...] with a literal name."""
import ast
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HELPERS = {"_model_list"}          # app/config.py: reads the variable it is given


def _environ(node: ast.AST) -> bool:
    return ast.unparse(node).endswith("environ") or ast.unparse(node) == "env"


def names_read() -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for path in [p for d in ("app", "backend") for p in (ROOT / d).rglob("*.py")]:
        for node in ast.walk(ast.parse(path.read_text())):
            key = None
            if isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant):
                f = node.func
                if isinstance(f, ast.Attribute) and (f.attr == "getenv" or (f.attr in ("get", "pop", "setdefault") and _environ(f.value))):
                    key = node.args[0].value
                elif isinstance(f, ast.Name) and f.id in HELPERS:
                    key = node.args[0].value
            elif isinstance(node, ast.Subscript) and _environ(node.value) and isinstance(node.slice, ast.Constant):
                key = node.slice.value
            if isinstance(key, str) and re.fullmatch(r"[A-Z][A-Z0-9_]+", key):
                out.setdefault(key, set()).add(str(path.relative_to(ROOT)))
    return out


def test_every_variable_the_code_reads_is_in_env_example():
    names = names_read()
    assert len(names) > 30, "the scan found the reads"   # 38 after the S5 removal
    example = (ROOT / ".env.example").read_text()
    missing = {k: sorted(v) for k, v in names.items() if not re.search(rf"\b{k}\b", example)}
    assert not missing, f"read in code, not in .env.example: {missing}"


def test_the_agent_step_budget_has_one_default():
    """In a fresh interpreter, so the module constants are read without AGENT_MAX_STEPS
    (reloading the module here would give other tests a second AgentAction class)."""
    env = {k: v for k, v in os.environ.items() if k != "AGENT_MAX_STEPS"}
    code = "import app.checks.agent as a, app.config as c; print(a.MAX_STEPS, c.DEFAULT_AGENT_STEPS)"
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True, check=True)
    assert len(set(out.stdout.split())) == 1, out.stdout
    assert "AGENT_MAX_STEPS=" not in re.sub(r"^#.*$", "", (ROOT / ".env.example").read_text(), flags=re.M), \
        ".env.example leaves it commented, so the code's default applies"
