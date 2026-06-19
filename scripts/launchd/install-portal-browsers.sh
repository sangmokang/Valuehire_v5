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
#
# 관리자 권한(sudo)이 필요 없다 — 사용자 LaunchAgent(~/Library/LaunchAgents)다.
set -euo pipefail

LABEL="com.valuehire.portal-browsers"
SRC_PLIST="$(cd "$(dirname "$0")" && pwd)/$LABEL.plist"
DEST_DIR="$HOME/Library/LaunchAgents"
DEST_PLIST="$DEST_DIR/$LABEL.plist"

cmd_install() {
  [[ -f "$SRC_PLIST" ]] || { echo "❌ plist 원본 없음: $SRC_PLIST"; exit 1; }
  mkdir -p "$DEST_DIR" "$HOME/.valuehire/logs"
  cp "$SRC_PLIST" "$DEST_PLIST"
  # 이미 로드돼 있으면 먼저 내린 뒤 다시 올린다(멱등).
  launchctl unload "$DEST_PLIST" 2>/dev/null || true
  launchctl load "$DEST_PLIST"
  echo "✅ 설치 완료 → 로그인 시 자동 시작 + 5분마다 죽은 창 되살림."
  echo "   상태 확인: scripts/portal_browsers.sh health"
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

case "${1:-}" in
  install)   cmd_install ;;
  uninstall) cmd_uninstall ;;
  status)    cmd_status ;;
  *) echo "사용법: $0 {install|uninstall|status}"; exit 2 ;;
esac
