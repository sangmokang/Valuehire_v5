#!/bin/zsh
set -euo pipefail

REPO_DIR="${VALUEHIRE_REPO_DIR:-/Users/kangsangmo/Desktop/Valuehire_v5}"
ARTIFACT_PATH="${VALUEHIRE_DRY_RUN_ARTIFACT:-$REPO_DIR/artifacts/multi_position_sourcing/dry-run-latest.json}"
MAX_AGE_SECONDS="${VALUEHIRE_HEALTH_MAX_ARTIFACT_AGE_SECONDS:-1800}"

if ! pgrep -f "valuehire-search-loop.sh" >/dev/null; then
  echo "search loop process is not running"
  exit 1
fi

if [[ ! -s "$ARTIFACT_PATH" ]]; then
  echo "dry-run artifact missing or empty: $ARTIFACT_PATH"
  exit 1
fi

now_epoch="$(date +%s)"
artifact_mtime="$(stat -f %m "$ARTIFACT_PATH")"
artifact_age="$((now_epoch - artifact_mtime))"

if (( artifact_age > MAX_AGE_SECONDS )); then
  echo "dry-run artifact is stale: ${artifact_age}s > ${MAX_AGE_SECONDS}s"
  exit 1
fi

echo "ok: search loop running; artifact age ${artifact_age}s"
