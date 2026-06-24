#!/usr/bin/env bash
# rps_switch.sh — LinkedIn 리크루터(RPS) "지금 내가 다른 PC에서 쓴다" 수동 스위치.
#
# 왜: LinkedIn RPS는 한 계정 = 한 브라우저 세션만 허용한다. 사장님이 다른 PC에서 RPS를
#     직접 쓰는 동안 이 맥의 자동화가 같은 계정에 붙으면 세션이 충돌하고 보안 확인이 뜬다.
#     이 스위치를 켜두면, 자동화는 LinkedIn만 건너뛰고 사람인·잡코리아는 계속 돈다.
#
# 사용법:
#   ./scripts/rps_switch.sh on       # 켜기 — 자동화가 LinkedIn 양보(다른 PC에서 RPS 쓸 때)
#   ./scripts/rps_switch.sh off      # 끄기 — 자동화가 다시 LinkedIn 사용
#   ./scripts/rps_switch.sh status   # 지금 상태 보기
#
# 플래그 파일 위치는 VALUEHIRE_RPS_IN_USE_FLAG 로 바꿀 수 있다(기본: ~/.valuehire/rps_in_use.flag).
set -euo pipefail

FLAG="${VALUEHIRE_RPS_IN_USE_FLAG:-$HOME/.valuehire/rps_in_use.flag}"

case "${1:-}" in
  on)
    mkdir -p "$(dirname "$FLAG")"
    : > "$FLAG"
    echo "✅ RPS 스위치 ON — 자동화는 이제 LinkedIn을 건너뜁니다(사람인·잡코리아는 계속)."
    echo "   다른 PC에서 RPS 다 쓰시면 'off' 로 꺼주세요.  ($FLAG)"
    ;;
  off)
    if [[ -e "$FLAG" ]]; then
      rm -f "$FLAG"
      echo "✅ RPS 스위치 OFF — 자동화가 다시 LinkedIn을 사용합니다."
    else
      echo "ℹ️ 이미 OFF 상태입니다(스위치 꺼져 있음)."
    fi
    ;;
  status)
    if [[ -e "$FLAG" ]]; then
      echo "🔴 RPS 스위치 ON — 자동화가 LinkedIn 양보 중. ($FLAG)"
    else
      echo "🟢 RPS 스위치 OFF — 자동화가 LinkedIn 사용 가능."
    fi
    ;;
  *)
    echo "사용법: $0 {on|off|status}"
    exit 2
    ;;
esac
