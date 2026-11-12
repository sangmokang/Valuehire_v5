#!/usr/bin/env bash
# strict 진입점 동기화 러너 (GitOps 배포 위생 — goal: docs/engineering/strict-unify-goal-2026-11-12.md)
#
#   tools/sync-strict-skill.sh --check                      정본↔설치본 해시 대조(쓰기 0). 드리프트 0 → exit 0, 아니면 1
#   tools/sync-strict-skill.sh --install [--remove-legacy]  병합된 리비전(HEAD == origin/main, 정본 clean)에서만 설치
#
# 정본(이 레포)                    → 설치 대상
#   skills/strict/                 → $CLAUDE_HOME/skills/strict   (기본 ~/.claude)
#   .codex/skills/strict/          → $CODEX_HOME/skills/strict    (기본 ~/.codex)
# legacy(폐지된 st 별칭): $CLAUDE_HOME/commands/st.md, $CODEX_HOME/skills/st
# 백업: <home>/.strict-backups/<ts>/  (skills/ 밖 — 스킬 로더가 백업을 중복 스킬로 읽지 않게). 삭제하지 않는다.
# exit: 0 성공/드리프트 0 · 1 드리프트 · 2 사용법 오류 · 3 설치 거부(승인 리비전 아님)
set -euo pipefail

usage() { echo "usage: $0 --check | --install [--remove-legacy]" >&2; exit 2; }

MODE=""; REMOVE_LEGACY=0
for a in "$@"; do
  case "$a" in
    --check) [ -z "$MODE" ] || usage; MODE=check ;;
    --install) [ -z "$MODE" ] || usage; MODE=install ;;
    --remove-legacy) REMOVE_LEGACY=1 ;;
    *) usage ;;
  esac
done
[ -n "$MODE" ] || usage
[ "$MODE" = install ] || [ "$REMOVE_LEGACY" = 0 ] || usage

ROOT=$(git -C "$(dirname "$0")" rev-parse --show-toplevel)
CLAUDE_HOME=${CLAUDE_HOME:-$HOME/.claude}
CODEX_HOME=${CODEX_HOME:-$HOME/.codex}

SRC=("$ROOT/skills/strict" "$ROOT/.codex/skills/strict")
DST=("$CLAUDE_HOME/skills/strict" "$CODEX_HOME/skills/strict")
ENGINE=(claude codex)
LEGACY=("$CLAUDE_HOME/commands/st.md" "$CODEX_HOME/skills/st")

# 디렉터리 트리 해시: 상대경로 + 내용. 설치 기록(.strict-*)은 제외.
tree_hash() {
  local d=$1
  [ -d "$d" ] || { echo "-"; return; }
  (cd "$d" && find . -type f ! -name '.strict-*' ! -name '.DS_Store' -print0 | LC_ALL=C sort -z |
    while IFS= read -r -d '' f; do printf '%s\0' "$f"; shasum -a 256 < "$f"; done) | shasum -a 256 | cut -c1-16
}

for s in "${SRC[@]}"; do [ -f "$s/SKILL.md" ] || { echo "정본 없음: $s" >&2; exit 2; }; done

report() {
  local drift=0 i
  for i in 0 1; do
    local sh dh state
    sh=$(tree_hash "${SRC[$i]}"); dh=$(tree_hash "${DST[$i]}")
    if [ "$dh" = "-" ]; then state=MISSING; drift=1
    elif [ "$sh" = "$dh" ]; then state=OK
    else state=DRIFT; drift=1; fi
    echo "${ENGINE[$i]}  $state  src=$sh  dest=$dh  (${DST[$i]})"
  done
  for l in "${LEGACY[@]}"; do
    if [ -e "$l" ]; then echo "LEGACY  present  $l  (폐지된 st 별칭 — --install --remove-legacy 로 백업 이동)"; drift=1; fi
  done
  return $drift
}

if [ "$MODE" = check ]; then
  echo "strict sync --check  (정본 commit $(git -C "$ROOT" rev-parse --short HEAD))"
  if report; then echo "드리프트 0"; exit 0; else echo "드리프트 있음"; exit 1; fi
fi

# ---------- install: 승인(병합)된 리비전에서만 ----------
HEAD=$(git -C "$ROOT" rev-parse HEAD)
MAIN=$(git -C "$ROOT" rev-parse -q --verify refs/remotes/origin/main || true)
if [ -z "$MAIN" ]; then echo "거부: origin/main 참조 없음 — git fetch 후 병합된 main에서 실행하세요" >&2; exit 3; fi
if [ "$HEAD" != "$MAIN" ]; then
  echo "거부: HEAD($HEAD)가 origin/main($MAIN)이 아님 — PR 병합 후 main에서만 설치합니다" >&2; exit 3
fi
if [ -n "$(git -C "$ROOT" status --porcelain -- skills/strict .codex/skills/strict tools/sync-strict-skill.sh)" ]; then
  echo "거부: 정본 경로에 미커밋 변경이 있음 — 커밋된 내용만 설치합니다" >&2; exit 3
fi

TS=$(date -u +%Y%m%dT%H%M%SZ)
echo "strict sync --install  commit $HEAD  ($TS)"
echo "[before]"; report || true
for i in 0 1; do
  dst=${DST[$i]}; parent=$(dirname "$dst"); home=$(dirname "$parent")
  mkdir -p "$parent"
  tmp=$(mktemp -d "$parent/.strict-staging-XXXXXX")
  cp -R "${SRC[$i]}/." "$tmp/"
  printf '{"commit":"%s","tree_hash":"%s","installed_at":"%s","engine":"%s"}\n' \
    "$HEAD" "$(tree_hash "${SRC[$i]}")" "$TS" "${ENGINE[$i]}" > "$tmp/.strict-install.json"
  if [ -e "$dst" ]; then
    mkdir -p "$home/.strict-backups/$TS"
    mv "$dst" "$home/.strict-backups/$TS/strict"
    echo "backup  ${ENGINE[$i]}  $home/.strict-backups/$TS/strict"
  fi
  mv "$tmp" "$dst"
done
if [ "$REMOVE_LEGACY" = 1 ]; then
  for l in "${LEGACY[@]}"; do
    [ -e "$l" ] || continue
    home=$(dirname "$(dirname "$l")")
    mkdir -p "$home/.strict-backups/$TS"
    mv "$l" "$home/.strict-backups/$TS/$(basename "$l")"
    echo "legacy  moved  $l → $home/.strict-backups/$TS/$(basename "$l")"
  done
fi
echo "[after]"
if report; then echo "설치 완료 — 드리프트 0"; exit 0; else echo "설치 후에도 드리프트 — 확인 필요" >&2; exit 1; fi
