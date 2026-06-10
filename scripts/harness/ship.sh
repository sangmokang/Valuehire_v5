#!/usr/bin/env bash
# 게이트 5 — 배송. verify 재실행 → push → PR. verify RED면 배송 금지.
set -euo pipefail
cd "$(dirname "$0")/../.."

echo "ship: verify 재실행 (게이트 4)..."
if ! ./verify.sh; then
  echo "ship: verify RED — 배송 중단. GREEN 만든 뒤 다시." >&2
  exit 1
fi

BRANCH=$(git rev-parse --abbrev-ref HEAD)
if [ "$BRANCH" = "main" ]; then
  echo "ship: main에서 직접 ship 금지. make task NAME=... 로 브랜치를 파세요." >&2
  exit 2
fi

echo "ship: push origin $BRANCH..."
git push -u origin "$BRANCH"

echo "ship: PR 생성..."
if command -v gh >/dev/null 2>&1; then
  gh pr create --fill || echo "ship: PR 생성 실패/이미 존재 — gh pr view 로 확인"
else
  echo "ship: gh 미설치 — PR 수동 생성 필요"
fi
