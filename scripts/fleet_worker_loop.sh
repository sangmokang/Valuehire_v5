#!/usr/bin/env bash
# 함대 워커 루프 — launchd/작업스케줄러가 이 스크립트를 상주 실행한다.
# VALUEHIRE_MACHINE 필수(fail-closed) — plist/스케줄러 env 로 주입.
set -uo pipefail
REPO_DIR="${VALUEHIRE_REPO_DIR:-/Users/kangsangmo/Valuehire_v5}"
cd "$REPO_DIR"

PY="$REPO_DIR/.venv/bin/python"
[ -x "$PY" ] || PY="python3"

exec "$PY" -m tools.multi_position_sourcing.fleet_worker "$@"
