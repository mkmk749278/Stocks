#!/usr/bin/env bash
# Run on the VPS by .github/workflows/deploy.yml.
# Idempotent: pull → install → migrate → restart.

set -euo pipefail

APP_DIR="${APP_DIR:-/opt/axiom/app}"
VENV="${VENV:-/opt/axiom/venv}"
BRANCH="${BRANCH:-main}"

echo "[deploy] pulling $BRANCH in $APP_DIR"
cd "$APP_DIR"
git fetch --all --prune
git checkout "$BRANCH"
git pull --ff-only origin "$BRANCH"

echo "[deploy] installing deps"
"$VENV/bin/pip" install --upgrade pip wheel
"$VENV/bin/pip" install -r requirements.txt

echo "[deploy] running alembic migrations"
"$VENV/bin/alembic" upgrade head

echo "[deploy] restarting supervisor programs"
sudo /usr/bin/supervisorctl restart axiom-api axiom-worker axiom-beat axiom-feed

echo "[deploy] done"
