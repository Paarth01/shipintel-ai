"""Static checks of deployment artefacts (the image itself cannot be built in every environment)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")
ROOT = Path(__file__).resolve().parent.parent


def read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


# ------------------------------------------------------------------ Dockerfile
def test_dockerfile_runs_as_a_non_root_user():
    d = read("Dockerfile")
    users = re.findall(r"^USER\s+(\S+)", d, re.M)
    assert users and users[-1] not in {"root", "0", "0:0"} and users[-1].split(":")[0].isdigit()


def test_dockerfile_installs_only_hash_verified_dependencies():
    d = read("Dockerfile")
    pip_lines = [ln for ln in d.splitlines() if "pip install" in ln]
    assert pip_lines and all("--require-hashes" in ln for ln in pip_lines)
    assert "-r requirements.lock" in d and "-r requirements-ocr.lock" in d


def test_dockerfile_basics():
    d = read("Dockerfile")
    assert "HEALTHCHECK" in d and "multi-stage" not in d.lower() or d.count("FROM ") >= 2
    assert not re.search(r"^FROM\s+\S+:latest", d, re.M) and "ADD http" not in d
    assert "SHIPINTEL_ENV=production" in d and "--no-server-header" in d
    assert "--no-access-log" in d  # our own structured access log replaces uvicorn's
    assert "apt-get install -y --no-install-recommends" in d and "rm -rf /var/lib/apt/lists" in d


def test_dockerignore_keeps_secrets_and_vcs_out_of_the_image():
    ignore = read(".dockerignore").splitlines()
    for entry in (".git", ".env", ".venv", "tests"):
        assert entry in ignore
    assert "!.env.example" in ignore


# ------------------------------------------------------------------ compose
def test_compose_services_are_hardened_and_loopback_bound():
    spec = yaml.safe_load(read("docker-compose.yml"))
    for name, svc in spec["services"].items():
        assert svc["read_only"] is True, name
        assert svc["cap_drop"] == ["ALL"], name
        assert "no-new-privileges:true" in svc["security_opt"], name
        assert svc["mem_limit"] and svc["pids_limit"], name
        assert all(p.startswith("127.0.0.1:") for p in svc["ports"]), (name, svc["ports"])
        assert any(t.startswith("/tmp") for t in svc["tmpfs"]), name


def test_compose_requires_secrets_from_the_environment_not_the_file():
    text = read("docker-compose.yml")
    assert re.search(r"SHIPINTEL_API_KEY:\s*\$\{SHIPINTEL_UI_API_KEY:\?", text)
    assert not re.search(r"SHIPINTEL_API_KEYS?:\s*[A-Za-z0-9_]{20,}", text)  # no literal secret


# ------------------------------------------------------------------ CI
def test_ci_workflow_structure_and_least_privilege():
    wf = yaml.safe_load(read(".github/workflows/ci.yml"))
    assert wf["permissions"] == {"contents": "read"}
    assert {"lint", "test", "security", "docker"} <= set(wf["jobs"])
    triggers = wf.get(True) or wf.get("on")  # PyYAML parses the bare key `on` as boolean True
    assert "schedule" in triggers and "pull_request" in triggers  # weekly advisory scan + PR checks
    text = read(".github/workflows/ci.yml")
    assert "pip-audit -r requirements.lock --require-hashes" in text
    assert "--fail-under=85" in text and "bandit -r app" in text and "mypy app" in text
    assert text.count("--require-hashes -r requirements-dev.lock") >= 3


def test_dependabot_covers_pip_actions_and_docker():
    spec = yaml.safe_load(read(".github/dependabot.yml"))
    assert {u["package-ecosystem"] for u in spec["updates"]} == {"pip", "github-actions", "docker"}


# ------------------------------------------------------------------ requirements / lockfiles
def test_runtime_requirements_contain_no_dev_tooling():
    runtime = read("requirements.txt").lower()
    for dev_only in (
        "pytest",
        "ruff",
        "mypy",
        "bandit",
        "reportlab",
        "coverage",
        "pip-audit",
        "pip-tools",
    ):
        assert dev_only not in runtime, dev_only


@pytest.mark.parametrize(
    "lock", ["requirements.lock", "requirements-ocr.lock", "requirements-dev.lock"]
)
def test_lockfiles_are_fully_pinned_with_hashes(lock):
    text = read(lock)
    reqs = re.findall(r"^([A-Za-z0-9_.\-\[\]]+)(==|>=|<=|~=|<|>)([^\s\\;]+)", text, re.M)
    assert len(reqs) > 30 and all(op == "==" for _, op, _ in reqs), (
        "every dependency must be pinned with =="
    )
    blocks = re.split(r"\n(?=[A-Za-z0-9_.\-\[\]]+==)", text)
    pinned = [b for b in blocks if re.match(r"[A-Za-z0-9_.\-\[\]]+==", b)]
    assert all("--hash=sha256:" in b for b in pinned), (
        "every pinned package needs at least one hash"
    )


def test_lockfiles_pin_patched_versions_of_known_advisories():
    dev = read("requirements-dev.lock")
    m = re.search(r"^pytest==(\d+)\.(\d+)\.(\d+)", dev, re.M)
    assert m and tuple(map(int, m.groups())) >= (9, 0, 3)  # CVE-2025-71176 fixed in 9.0.3


def test_ocr_lock_extends_runtime_lock():
    rt = set(re.findall(r"^([A-Za-z0-9_.\-]+)==", read("requirements.lock"), re.M))
    ocr = set(re.findall(r"^([A-Za-z0-9_.\-]+)==", read("requirements-ocr.lock"), re.M))
    assert rt <= ocr and {"pytesseract", "pillow"} <= {n.lower() for n in ocr}


def test_env_example_documents_every_setting_the_code_reads():
    code = read("app/config.py")
    used = set(re.findall(r'"(SHIPINTEL_[A-Z_]+)"', code))
    documented = set(re.findall(r"SHIPINTEL_[A-Z_]+", read(".env.example")))
    missing = used - documented
    assert not missing, f"settings missing from .env.example: {sorted(missing)}"


def test_operations_doc_mentions_every_setting():
    code = read("app/config.py")
    used = set(re.findall(r'"(SHIPINTEL_[A-Z_]+)"', code))
    ops = read("docs/operations.md")
    # abbreviated groups in the doc (e.g. `SHIPINTEL_OCR_ENABLED` / `SHIPINTEL_NLP_ENABLED`) still name the variable
    missing = {v for v in used if v not in ops and v.replace("SHIPINTEL_", "") not in ops}
    assert not missing, sorted(missing)
