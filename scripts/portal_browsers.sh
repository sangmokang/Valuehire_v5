#!/usr/bin/env bash
# portal_browsers.sh — 사람인/잡코리아/링크드인 디버그 크롬을 "안 꺼지게" 띄우는 독립 런처.
#
# 이 스크립트는 Claude 세션이나 특정 터미널 창에 묶이지 않는다.
# nohup 으로 띄우므로 터미널을 닫아도 크롬 창은 계속 살아 있다.
# 저장된 로그인 프로필을 재사용하고, CDP(원격 디버깅) 포트를 IPv4(127.0.0.1)로 고정한다.
#
# launchd(자동 시작/되살리기)로 상주시키려면:
#   scripts/launchd/install-portal-browsers.sh install
#
# 사용법:
#   ./scripts/portal_browsers.sh start     # 3개 창 띄우기 (이미 떠 있으면 건너뜀 = 멱등)
#   ./scripts/portal_browsers.sh status     # 포트별 살아있는지/현재 URL 확인
#   ./scripts/portal_browsers.sh health     # 채널별 로그인 상태 점검(로그인됨/로그인 필요)
#   ./scripts/portal_browsers.sh stop        # 3개 창 종료
#   ./scripts/portal_browsers.sh restart     # 종료 후 재시작
#
# 안전 규칙(SOT):
#  - 캡차/2FA/보안문자는 절대 자동으로 풀지 않는다 — 사람이 그 창에서 처리.
#  - 제안/메일 "보내기"는 자동화하지 않는다. 검색/수집까지만.
#  - CDP 포트는 127.0.0.1 에만 묶는다(외부 노출 금지 — 무인증 원격조종 취약점).
set -euo pipefail

# ── 설정 (필요하면 환경변수로 덮어쓰기) ────────────────────────────────
CHROME="${PORTAL_CHROME:-$HOME/Library/Caches/ms-playwright/chromium-1223/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing}"
LOG_DIR="${PORTAL_LOG_DIR:-$HOME/.valuehire/logs}"

SARAMIN_PORT="${SARAMIN_PORT:-9223}"
JOBKOREA_PORT="${JOBKOREA_PORT:-9224}"
LINKEDIN_PORT="${LINKEDIN_PORT:-9225}"   # 9222는 다른 크롬과 충돌나서 깨끗한 포트 사용

SARAMIN_PROFILE="${SARAMIN_PROFILE:-$HOME/.valuehire/portal_profiles/saramin/default}"
JOBKOREA_PROFILE="${JOBKOREA_PROFILE:-$HOME/.valuehire/portal_profiles/jobkorea/default}"
LINKEDIN_PROFILE="${LINKEDIN_PROFILE:-$HOME/.valuehire/cdp_profiles/linkedin}"

# 로그인 프로필을 재사용하므로 검색 페이지로 직접 이동한다(미로그인 시 포털이 로그인으로 보냄).
SARAMIN_URL="https://www.saramin.co.kr/zf_user/memcom/talent-pool/main/search"
JOBKOREA_URL="https://www.jobkorea.co.kr/Corp/Person/Find"
LINKEDIN_URL="https://www.linkedin.com/talent/home"

# 채널 목록: "이름 포트 프로필 URL"
CHANNELS=(
  "saramin   $SARAMIN_PORT   $SARAMIN_PROFILE   $SARAMIN_URL"
  "jobkorea  $JOBKOREA_PORT  $JOBKOREA_PROFILE  $JOBKOREA_URL"
  "linkedin  $LINKEDIN_PORT  $LINKEDIN_PROFILE  $LINKEDIN_URL"
)
# 로그인 안 된 화면을 가리키는 URL 신호(소문자 비교).
LOGIN_HINTS='login|/auth|signin|sign-in|checkpoint|authwall|uas/login'
# ──────────────────────────────────────────────────────────────────────

cdp_alive() { curl -s --max-time 2 "http://127.0.0.1:$1/json/version" >/dev/null 2>&1; }

cdp_url() {
  curl -s --max-time 2 "http://127.0.0.1:$1/json" 2>/dev/null \
    | grep -oE '"url": *"https?://[^"]*"' | head -1 | sed -E 's/.*"(https?:[^"]*)"/\1/' | cut -c1-120
}

start_one() {
  local name="$1" port="$2" profile="$3" url="$4"
  if cdp_alive "$port"; then
    echo "  [$name] 이미 :$port 에서 실행 중 — 건너뜀"
    return 0
  fi
  # 탭 증식 가드(issue #71): 같은 프로필의 크롬 프로세스가 이미 살아 있으면(기동 중·절전 직후 등
  # CDP만 잠깐 무응답) 바이너리를 다시 실행하지 않는다 — 재실행하면 기존 인스턴스에 새 탭만 쌓인다.
  if pgrep -f -- "--user-data-dir=$profile" >/dev/null 2>&1; then
    echo "  [$name] ⚠️ 크롬 프로세스는 살아있는데 CDP :$port 무응답 — 재실행하지 않음(탭 증식 방지). 계속 무응답이면 'restart'."
    return 0
  fi
  if [[ ! -d "$profile" ]]; then
    echo "  [$name] ⚠️ 프로필 폴더 없음: $profile (로그인 후 자동 생성됨)"
    mkdir -p "$profile"
  fi
  mkdir -p "$LOG_DIR"
  nohup "$CHROME" \
    --remote-debugging-port="$port" \
    --remote-debugging-address=127.0.0.1 \
    --user-data-dir="$profile" \
    --no-first-run --no-default-browser-check \
    --disable-session-crashed-bubble --restore-last-session=false \
    "$url" \
    >"$LOG_DIR/portal_$name.log" 2>&1 &
  disown || true
  echo "  [$name] 띄움 → CDP http://127.0.0.1:$port  (로그: $LOG_DIR/portal_$name.log)"
}

cmd_start() {
  [[ -x "$CHROME" ]] || { echo "❌ 크롬 실행파일 없음: $CHROME"; exit 1; }
  echo "▶ 디버그 크롬 시작…"
  for row in "${CHANNELS[@]}"; do
    # shellcheck disable=SC2086
    set -- $row; start_one "$1" "$2" "$3" "$4"
  done
  local boot_wait="${PORTAL_BOOT_WAIT:-20}"
  echo "⏳ 기동 확인(최대 ${boot_wait}초)…"
  for row in "${CHANNELS[@]}"; do
    set -- $row; local name="$1" port="$2" n=0
    until cdp_alive "$port" || [[ $n -ge $boot_wait ]]; do sleep 1; n=$((n+1)); done
    if cdp_alive "$port"; then echo "  ✅ $name :$port 응답"; else echo "  ❌ $name :$port 무응답 — 로그 확인"; fi
  done
  echo "✔ 완료. 'health'로 로그인 상태를 확인하고, 안 된 채널은 그 창에서 직접 로그인하세요."
}

cmd_status() {
  for row in "${CHANNELS[@]}"; do
    set -- $row; local name="$1" port="$2"
    if cdp_alive "$port"; then
      echo "  ✅ $name :$port  | 현재 URL: $(cdp_url "$port")"
    else
      echo "  ❌ $name :$port  (안 떠 있음)"
    fi
  done
}

# 로그인 상태 점검 — 자동 로그인/캡차 풀이는 하지 않는다(SOT). 사람이 볼 보고만 한다.
cmd_health() {
  local need_login=0 down=0
  echo "🔎 채널별 로그인 상태 점검 (자동 로그인하지 않음 — 필요 시 그 창에서 직접):"
  for row in "${CHANNELS[@]}"; do
    set -- $row; local name="$1" port="$2"
    if ! cdp_alive "$port"; then
      echo "  ❌ $name : 창이 안 떠 있음 → 'start' 필요"
      down=$((down+1)); continue
    fi
    local url lurl
    url="$(cdp_url "$port")"
    lurl="$(printf '%s' "$url" | tr '[:upper:]' '[:lower:]')"
    if printf '%s' "$lurl" | grep -qE "$LOGIN_HINTS"; then
      echo "  ⚠️ $name : 로그인 필요 — 그 창에서 직접 로그인하세요 ($url)"
      need_login=$((need_login+1))
    else
      echo "  ✅ $name : 로그인된 것으로 보임 ($url)"
    fi
  done
  if [[ $down -gt 0 || $need_login -gt 0 ]]; then
    echo "→ 조치 필요: 안 뜬 창 $down개, 로그인 필요 $need_login개."
    return 1
  fi
  echo "→ 3사 모두 정상."
  return 0
}

cmd_stop() {
  echo "■ 디버그 크롬 종료…"
  for row in "${CHANNELS[@]}"; do
    set -- $row; local name="$1" port="$2"
    if pkill -f "remote-debugging-port=$port" 2>/dev/null; then
      echo "  [$name] 종료"
    else
      echo "  [$name] 실행 중 아님"
    fi
  done
}

case "${1:-}" in
  start)   cmd_start ;;
  status)  cmd_status ;;
  health)  cmd_health ;;
  stop)    cmd_stop ;;
  restart) cmd_stop; sleep 2; cmd_start ;;
  *) echo "사용법: $0 {start|status|health|stop|restart}"; exit 2 ;;
esac
