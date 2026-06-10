#!/usr/bin/env bash
# 게이트 2 — worktree를 판다. 인수기준을 실패시키는 RED 테스트부터 작성할 자리.
# ledger에 RED로 등록 → GREEN 될 때까지 게이트 0가 추적.
set -euo pipefail
cd "$(dirname "$0")/../.."

NAME="${1:?usage: task.sh <slug>}"
SLUG=$(printf '%s' "$NAME" | tr ' /' '--' | tr -cd 'a-zA-Z0-9._-')
BRANCH="task/$SLUG"
WT="../Valuehire_v5-$SLUG"

if [ -e "$WT" ]; then
  echo "task: worktree가 이미 존재합니다: $WT" >&2
  exit 1
fi

if git show-ref --verify --quiet "refs/heads/$BRANCH"; then
  git worktree add "$WT" "$BRANCH"
else
  git worktree add -b "$BRANCH" "$WT"
fi

mkdir -p .harness
touch .harness/red-ledger.tsv
printf '%s\tRED\t-\tworktree %s (branch %s)\n' "$SLUG" "$WT" "$BRANCH" >> .harness/red-ledger.tsv

echo "task: worktree 생성 → $WT (branch $BRANCH)"
echo "      다음: cd $WT && 인수기준 RED 테스트 작성 → 커밋(RED 확인)"
