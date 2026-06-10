#!/usr/bin/env bash
# pre-push 훅을 .git/hooks 에 설치 (심볼릭이 아니라 복사 — 정본은 scripts/harness/pre-push).
set -euo pipefail
cd "$(dirname "$0")/../.."
HOOK_DIR="$(git rev-parse --git-path hooks)"
mkdir -p "$HOOK_DIR"
cp scripts/harness/pre-push "$HOOK_DIR/pre-push"
chmod +x "$HOOK_DIR/pre-push"
echo "install-hooks: $HOOK_DIR/pre-push 설치 완료"
