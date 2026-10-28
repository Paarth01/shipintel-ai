#!/usr/bin/env bash
# Runs the same checks as .github/workflows/ci.yml (everything except the Docker job).
# Usage: scripts/ci_local.sh            (uses `python` from the active environment)
#        PYTHON=/path/to/python scripts/ci_local.sh
set -euo pipefail
PY="${PYTHON:-python}"
step() { printf '\n=== %s\n' "$1"; }

step "lint: ruff check";  "$PY" -m ruff check app tests scripts
step "lint: ruff format"; "$PY" -m ruff format --check app tests scripts
step "types: mypy";       "$PY" -m mypy app
step "security: bandit";  "$PY" -m bandit -q -r app -ll
step "security: pip-audit (runtime lock)"
"$PY" -m pip_audit -r requirements.lock --require-hashes --no-deps --disable-pip
step "security: pip-audit (dev lock)"
"$PY" -m pip_audit -r requirements-dev.lock --require-hashes --no-deps --disable-pip
step "tests + coverage gate (>= 85%)"
"$PY" -m coverage run --branch --source=app -m pytest
"$PY" -m coverage report --skip-empty --fail-under=85
step "synthetic data generator is deterministic"
TMP="$(mktemp -d)"
"$PY" scripts/generate_synthetic_data.py --out "$TMP/a" > /dev/null
"$PY" scripts/generate_synthetic_data.py --out "$TMP/b" > /dev/null
diff -r "$TMP/a/annotations" "$TMP/b/annotations" && echo "identical"
rm -rf "$TMP"
printf '\nALL CHECKS PASSED\n'
