#!/usr/bin/env bash
# 함대 워커 루프 — launchd/작업스케줄러가 이 스크립트를 상주 실행한다.
# VALUEHIRE_MACHINE 필수(fail-closed) — plist/스케줄러 env 로 주입.
# QA(2026-07-13): 경로가 틀리면 조용한 크래시-루프(launchd KeepAlive 무한재시작)가
# 되던 것을 pc-k6 규율로 봉인 — 명시 로그 + fail-soft 재시도, 자기위치 폴백.
set -uo pipefail

SCRIPT_SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
SELF_REPO_DIR="$(dirname "$SCRIPT_SELF_DIR")"
REPO_DIR="${VALUEHIRE_REPO_DIR:-$SELF_REPO_DIR}"

RETRY_SECONDS="${FLEET_LOOP_RETRY_SECONDS:-60}"
MAX_RETRIES="${FLEET_LOOP_MAX_RETRIES:-}"   # 빈 값 = 무한(launchd 상주용)

attempt=0
until [ -d "$REPO_DIR/tools/multi_position_sourcing" ] && cd "$REPO_DIR"; do
  attempt=$((attempt + 1))
  echo "[fleet-loop] 레포 경로 무효: $REPO_DIR (시도 $attempt) — VALUEHIRE_REPO_DIR 확인 필요" >&2
  # 주입 경로가 틀렸어도 스크립트 자기위치 레포가 유효하면 그쪽으로 폴백(드리프트 흡수).
  if [ "$REPO_DIR" != "$SELF_REPO_DIR" ] && [ -d "$SELF_REPO_DIR/tools/multi_position_sourcing" ]; then
    echo "[fleet-loop] 자기위치 레포로 폴백: $SELF_REPO_DIR" >&2
    REPO_DIR="$SELF_REPO_DIR"
    continue
  fi
  if [ -n "$MAX_RETRIES" ] && [ "$attempt" -ge "$MAX_RETRIES" ]; then
    echo "[fleet-loop] 재시도 한도($MAX_RETRIES) 소진 — 종료" >&2
    exit 1
  fi
  sleep "$RETRY_SECONDS"
done

PY="$REPO_DIR/.venv/bin/python"
[ -x "$PY" ] || PY="python3"

exec "$PY" -m tools.multi_position_sourcing.fleet_worker "$@"
