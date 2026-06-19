#!/usr/bin/env bash
# install-portal-browsers.sh — 3사 로그인 상주 서비스를 사용자 LaunchAgent 로 설치/해제한다.
#
# 설치하면: 맥에 로그인할 때마다 사람인·잡코리아·링크드인 디버그 크롬이 자동으로 뜨고,
#           5분마다 점검해 죽은 창을 되살린다. (캡차/2FA는 자동으로 풀지 않음 — SOT)
#
# 사용법:
#   scripts/launchd/install-portal-browsers.sh install     # 설치 + 즉시 시작
#   scripts/launchd/install-portal-browsers.sh uninstall   # 해제(자동 시작 끔)
#   scripts/launchd/install-portal-browsers.sh status      # 등록 상태 확인
#   scripts/launchd/install-portal-browsers.sh render DEST  # (검증용) launchctl 없이 plist만 생성+검증
#
# 관리자 권한(sudo)이 필요 없다 — 사용자 LaunchAgent(~/Library/LaunchAgents)다.
set -euo pipefail

LABEL="com.valuehire.portal-browsers"
HERE="$(cd "$(dirname "$0")" && pwd)"
SRC_PLIST="$HERE/$LABEL.plist"
# 런처는 이 설치 스크립트와 같은 레포의 scripts/portal_browsers.sh 다(경로 하드코딩 금지).
# 테스트용으로 PORTAL_LAUNCHER_OVERRIDE 로 덮어쓸 수 있다.
LAUNCHER="${PORTAL_LAUNCHER_OVERRIDE:-$(cd "$HERE/.." && pwd)/portal_browsers.sh}"
DEST_DIR="$HOME/Library/LaunchAgents"
DEST_PLIST="$DEST_DIR/$LABEL.plist"

# plist 템플릿의 ProgramArguments 를 실제 런처 절대경로로 채워 dest 에 기록한다.
# sed 대신 plistlib 로 정확히 기록한다 — 경로에 |, \, &, 공백 등 어떤 문자가 있어도 손상 없음.
# 기록 후 되읽어 ProgramArguments[0] 이 정확히 LAUNCHER 이고 실행가능한지 검증한다(설치 경로 직접 확인).
render_plist() {
  local dest="$1"
  [[ -f "$SRC_PLIST" ]] || { echo "❌ plist 원본 없음: $SRC_PLIST"; return 1; }
  [[ -x "$LAUNCHER" ]] || { echo "❌ 런처가 없거나 실행 불가: $LAUNCHER"; return 1; }
  # plistlib 로 정확히 기록하고, 같은 파이썬 안에서 되읽어 정확 비교한다.
  # 쉘 변수치환($())을 거치지 않으므로 개행·특수문자에도 검증이 새지 않는다.
  if ! PORTAL_SRC="$SRC_PLIST" PORTAL_DST="$dest" PORTAL_LAUNCHER="$LAUNCHER" python3 - <<'PY'
import os, plistlib, sys
launcher = os.environ["PORTAL_LAUNCHER"]
# 기록 직전에 다시 실행가능 여부 확인(검사와 사용을 인접시켜 시간차 창 최소화).
if not (os.path.isfile(launcher) and os.access(launcher, os.X_OK)):
    sys.exit("launcher missing or not executable at write time: %s" % launcher)
with open(os.environ["PORTAL_SRC"], "rb") as f:
    data = plistlib.load(f)
data["ProgramArguments"] = [launcher, "start"]
with open(os.environ["PORTAL_DST"], "wb") as f:
    plistlib.dump(data, f)
# 되읽어 기록된 ProgramArguments 가 의도와 정확히 일치하는지 검증.
with open(os.environ["PORTAL_DST"], "rb") as f:
    back = plistlib.load(f)
if back.get("ProgramArguments") != [launcher, "start"]:
    sys.exit("ProgramArguments mismatch after write")
PY
  then
    echo "❌ plist 생성/검증 실패"; rm -f "$dest"; return 1
  fi
}

cmd_install() {
  mkdir -p "$DEST_DIR" "$HOME/.valuehire/logs"
  render_plist "$DEST_PLIST" || exit 1
  # 이미 로드돼 있으면 먼저 내린 뒤 다시 올린다(멱등).
  launchctl unload "$DEST_PLIST" 2>/dev/null || true
  launchctl load "$DEST_PLIST"
  echo "✅ 설치 완료 → 로그인 시 자동 시작 + 5분마다 죽은 창 되살림."
  echo "   실행 런처: $LAUNCHER"
  echo "   상태 확인: $LAUNCHER health"
}

cmd_uninstall() {
  if [[ -f "$DEST_PLIST" ]]; then
    launchctl unload "$DEST_PLIST" 2>/dev/null || true
    rm -f "$DEST_PLIST"
    echo "✅ 해제 완료 — 자동 시작을 껐습니다(이미 떠 있는 창은 그대로). 'stop'으로 닫을 수 있습니다."
  else
    echo "이미 설치돼 있지 않습니다: $DEST_PLIST"
  fi
}

cmd_status() {
  if launchctl list 2>/dev/null | grep -q "$LABEL"; then
    echo "✅ 등록됨: $LABEL (자동 시작 켜짐)"
  else
    echo "❌ 등록 안 됨: $LABEL (자동 시작 꺼짐)"
  fi
  [[ -f "$DEST_PLIST" ]] && echo "   plist: $DEST_PLIST" || echo "   plist 미설치"
}

cmd_render() {
  local dest="${1:?usage: render <dest>}"
  render_plist "$dest" && echo "✅ render OK → $dest ($LAUNCHER)"
}

case "${1:-}" in
  install)   cmd_install ;;
  uninstall) cmd_uninstall ;;
  status)    cmd_status ;;
  render)    cmd_render "${2:-}" ;;
  *) echo "사용법: $0 {install|uninstall|status|render DEST}"; exit 2 ;;
esac
