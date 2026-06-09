#!/bin/zsh
set -euo pipefail

REPO_DIR="${VALUEHIRE_REPO_DIR:-/Users/kangsangmo/Desktop/Valuehire_v5}"
INTERVAL_SECONDS="${VALUEHIRE_SEARCH_INTERVAL_SECONDS:-900}"
ARTIFACT_DIR="${VALUEHIRE_ARTIFACT_DIR:-$REPO_DIR/artifacts/multi_position_sourcing}"
LOG_DIR="${VALUEHIRE_LOG_DIR:-$REPO_DIR/logs}"

mkdir -p "$ARTIFACT_DIR" "$LOG_DIR"
cd "$REPO_DIR"

while true; do
  started_at="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  echo "[$started_at] valuehire search cycle start"

  if /usr/bin/python3 -m tools.multi_position_sourcing.dry_run \
    --output "$ARTIFACT_DIR/dry-run-latest.json"; then
    finished_at="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
    echo "[$finished_at] valuehire search cycle ok"
  else
    failed_at="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
    echo "[$failed_at] valuehire search cycle failed" >&2
  fi

  sleep "$INTERVAL_SECONDS"
done
