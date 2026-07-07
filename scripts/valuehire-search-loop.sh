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
PYTHON_BIN="${VALUEHIRE_PYTHON_BIN:-/usr/bin/python3}"
SEARCH_EXECUTOR="${VALUEHIRE_SEARCH_EXECUTOR:-dry_run}"
SEARCH_SEGMENTS="${VALUEHIRE_SEARCH_SEGMENTS:-it_ai_data,marketing_growth,sales_bd,hr_finance_ops}"
SEARCH_MACHINE="${VALUEHIRE_SEARCH_MACHINE:-macmini}"

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

  started_at="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  echo "[$started_at] valuehire search cycle start"

  RUN_ID="${VALUEHIRE_SEARCH_RUN_ID:-search-$(date -u '+%Y%m%dT%H%M%SZ')}"
  TODAY="${VALUEHIRE_SEARCH_TODAY:-$(date -u '+%Y-%m-%d')}"
  command=()
  command_error=""

  case "$SEARCH_EXECUTOR" in
    dry_run|"")
      command=(
        "$PYTHON_BIN" -m tools.multi_position_sourcing.dry_run
        --output "$ARTIFACT_DIR/dry-run-latest.json"
      )
      ;;
    fake|live)
      command=(
        "$PYTHON_BIN" -m tools.multi_position_sourcing.harvest_driver
        --executor "$SEARCH_EXECUTOR"
        --segments "$SEARCH_SEGMENTS"
        --machine "$SEARCH_MACHINE"
        --run-id "$RUN_ID"
        --today "$TODAY"
        --log-root "$LOG_DIR"
        --output "$ARTIFACT_DIR/harvest-${SEARCH_EXECUTOR}-latest.json"
      )
      if [[ "$SEARCH_EXECUTOR" == "live" ]]; then
        KEYWORDS_JSON="${VALUEHIRE_SEARCH_KEYWORDS_JSON:-}"
        if [[ -z "$KEYWORDS_JSON" ]]; then
          command_error="VALUEHIRE_SEARCH_KEYWORDS_JSON is required when VALUEHIRE_SEARCH_EXECUTOR=live"
        else
          command+=(--keywords-json "$KEYWORDS_JSON")
        fi
      fi
      if [[ -n "${VALUEHIRE_SEARCH_SKIP_OWNER_CHECK:-}" ]]; then
        command+=(--skip-owner-check)
      fi
      ;;
    *)
      command_error="unsupported VALUEHIRE_SEARCH_EXECUTOR: $SEARCH_EXECUTOR"
      ;;
  esac

  if [[ -n "${VALUEHIRE_SEARCH_LOOP_PRINT_COMMAND:-}" ]]; then
    if [[ -n "$command_error" ]]; then
      echo "$command_error" >&2
      exit 2
    fi
    printf '%q ' "${command[@]}"
    echo
    exit 0
  fi

  cycle_status=0
  if [[ -n "$command_error" ]]; then
    echo "[$started_at] ERROR: $command_error" >&2
    cycle_status=2
  elif "${command[@]}"; then
    finished_at="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
    echo "[$finished_at] valuehire search cycle ok"
  else
    failed_at="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
    echo "[$failed_at] valuehire search cycle failed" >&2
    cycle_status=1
  fi

  if [[ -n "${VALUEHIRE_SEARCH_LOOP_ONCE:-}" ]]; then
    exit "$cycle_status"
  fi

  sleep "$INTERVAL_SECONDS"
done
