#!/usr/bin/env bash
# 게이트 0 — 미해결 RED 점검. 하나라도 있으면 exit 1 (새 작업 시작 금지).
# RED 원천 2가지: (1) .harness/red-ledger.tsv 에 RED로 등록된 작업, (2) 현재 verify 실패.
set -uo pipefail
cd "$(dirname "$0")/../.."
LEDGER=".harness/red-ledger.tsv"
red=0

echo "== Harness Red-Ledger =="

# (1) 추적된 열린 RED 작업
if [ -f "$LEDGER" ]; then
  while IFS=$'\t' read -r task status issue note; do
    [[ -z "${task:-}" || "$task" == \#* ]] && continue
    if [ "${status:-}" = "RED" ]; then
      echo "  RED  ${task}  (${issue:-no-issue})  ${note:-}"
      red=1
    fi
  done < "$LEDGER"
fi

# (2) 추적 안 된 RED: verify가 깨져 있으면 그것도 RED
if ! ./verify.sh >/tmp/harness-verify.log 2>&1; then
  echo "  RED  verify.sh  (현재 테스트 실패)"
  tail -3 /tmp/harness-verify.log | sed 's/^/        /'
  red=1
fi

if [ "$red" -eq 0 ]; then
  echo "  (clean) 미해결 RED 없음 — 새 작업 시작 가능"
  exit 0
fi

echo "== 미해결 RED 존재 — 먼저 닫을 것 (Gate 0) =="
exit 1
