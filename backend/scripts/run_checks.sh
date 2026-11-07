#!/usr/bin/env bash
# Run from backend/ with the venv active:  bash scripts/run_checks.sh   (backend must be running for step 3)
set -e
echo "== 1/3 backend tests"; python -m pytest -q
echo "== 2/3 frontend production build"; (cd ../frontend && npm install --no-audit --no-fund && npm run build)
echo "== 3/3 API smoke"; python scripts/smoke_check.py --base-url "${BASE_URL:-http://127.0.0.1:8000}"
