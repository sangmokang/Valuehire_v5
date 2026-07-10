#!/bin/zsh
set -uo pipefail

SCRIPT_SELF_DIR="$(cd "$(dirname "$0")/.." && pwd)"
REPO_DIR="${VALUEHIRE_REPO_DIR:-$SCRIPT_SELF_DIR}"

if [[ -n "${VALUEHIRE_SEARCH_LOOP_PRINT_REPO_DIR:-}" ]]; then
  echo "$REPO_DIR"
  exit 0
fi

INTERVAL_SECONDS="${VALUEHIRE_SEARCH_INTERVAL_SECONDS:-900}"
RETRY_BACKOFF_SECONDS="${VALUEHIRE_SEARCH_RETRY_BACKOFF_SECONDS:-30}"

while true; do
  if [[ ! -d "$REPO_DIR" ]]; then
    invalid_at="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
    echo "[$invalid_at] ERROR: REPO_DIR not found: $REPO_DIR — fail-soft, retrying in ${RETRY_BACKOFF_SECONDS}s" >&2
    sleep "$RETRY_BACKOFF_SECONDS"
    continue
  fi

  ARTIFACT_DIR="${VALUEHIRE_ARTIFACT_DIR:-$REPO_DIR/artifacts/multi_position_sourcing}"
  LOG_DIR="${VALUEHIRE_LOG_DIR:-$REPO_DIR/logs}"

  if ! mkdir -p "$ARTIFACT_DIR" "$LOG_DIR" || ! cd "$REPO_DIR"; then
    setup_failed_at="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
    echo "[$setup_failed_at] ERROR: failed to prepare artifact/log dir or cd into REPO_DIR: $REPO_DIR — fail-soft, retrying in ${RETRY_BACKOFF_SECONDS}s" >&2
    sleep "$RETRY_BACKOFF_SECONDS"
    continue
  fi

  if ! PYTHONPATH="$REPO_DIR${PYTHONPATH:+:$PYTHONPATH}" /usr/bin/python3 \
    -m tools.multi_position_sourcing.search_machine validate \
    --machine-id "${VALUEHIRE_SEARCH_MACHINE_ID:-}" >/dev/null; then
    echo "VALUEHIRE_SEARCH_MACHINE_ID is required or invalid; refusing to start search loop" >&2
    exit 2
  fi

  started_at="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  echo "[$started_at] valuehire search cycle start machine=${VALUEHIRE_SEARCH_MACHINE_ID}"

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
