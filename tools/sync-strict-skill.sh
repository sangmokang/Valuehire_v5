#!/usr/bin/env bash
# strict 진입점 동기화 러너 (GitOps 배포 위생 — goal: docs/engineering/strict-unify-goal-2026-11-12.md)
#
#   tools/sync-strict-skill.sh --check                      정본(HEAD 커밋)↔설치본 해시 대조. 설치 대상 쓰기 0.
#                                                          드리프트 0 → exit 0, 드리프트 → 1
#   tools/sync-strict-skill.sh --install [--remove-legacy]  병합된 리비전(HEAD == origin/main, 정본 clean)에서만 설치
#
# 정본(이 레포, HEAD 커밋 객체 기준)  → 설치 대상
#   skills/strict/                    → $CLAUDE_HOME/skills/strict   (기본 ~/.claude)
#   .codex/skills/strict/             → $CODEX_HOME/skills/strict    (기본 ~/.codex)
# legacy(폐지된 st 별칭): $CLAUDE_HOME/commands/st.md, $CODEX_HOME/skills/st
#
# 안전장치(Codex V1 2026-11-12 반영)
# - 설치 내용은 작업트리가 아니라 HEAD 커밋 객체에서 `git archive`로 꺼낸다(ignored·untracked 혼입 0).
# - 락($CLAUDE_HOME/.strict-sync.lock, mkdir 원자성)으로 동시 설치를 거부한다.
# - 두 대상을 모두 준비·검증한 뒤에만 교체한다. 교체 중 실패하면 이미 바꾼 대상을 백업에서 되돌린다.
# - 백업: <home>/.strict-backups/<UTC ts>-<pid>-<rand>/ (skills/ 밖, 이름 충돌 없음). 삭제하지 않는다.
# - 해시 실패·빈 해시는 비교하지 않고 exit 4로 거부한다.
# - 테스트 전용 장애 주입 STRICT_SYNC_FAULT(쉼표 목록: activate:<i>, restore:<i>, sigterm:<i>,
#   sigterm-after-backup:<i>, hash:stage) —
#   실패를 일으키는 방향으로만 동작한다(성공 경로를 열지 않음).
# exit: 0 성공/드리프트 0 · 1 드리프트 · 2 사용법 · 3 설치 거부(승인 리비전 아님/락) · 4 판독 실패
#       5 설치 실패(복원 완료) · 6 설치 실패 + 복원 실패(미복원 대상·백업 위치를 stderr에 명시) · 7 신호로 중단(복원 시도)
set -euo pipefail

usage() { echo "usage: $0 --check | --install [--remove-legacy]" >&2; exit 2; }
die() { echo "오류: $2" >&2; exit "$1"; }
FAULT=",${STRICT_SYNC_FAULT:-},"
fault() { case "$FAULT" in *",$1,"*) return 0 ;; *) return 1 ;; esac; }

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

ROOT=$(git -C "$(dirname "$0")" rev-parse --show-toplevel) || die 4 "레포 판독 실패"
CLAUDE_HOME=${CLAUDE_HOME:-$HOME/.claude}
CODEX_HOME=${CODEX_HOME:-$HOME/.codex}
HEAD=$(git -C "$ROOT" rev-parse --verify HEAD) || die 4 "HEAD 판독 실패"

REL=("skills/strict" ".codex/skills/strict")
DST=("$CLAUDE_HOME/skills/strict" "$CODEX_HOME/skills/strict")
ENGINE=(claude codex)
LEGACY=("$CLAUDE_HOME/commands/st.md" "$CODEX_HOME/skills/st")

WORK=$(mktemp -d "${TMPDIR:-/tmp}/strict-sync.XXXXXX") || die 4 "임시 디렉터리 생성 실패"
LOCK=""; STAGE=()
cleanup() {
  local s
  rm -rf "$WORK"
  for s in "${STAGE[@]+"${STAGE[@]}"}"; do [ ! -d "$s" ] || rm -rf "$s"; done  # 남은 스테이징(실패 시) 제거
  [ -z "$LOCK" ] || rmdir "$LOCK" 2>/dev/null || true
}
trap cleanup EXIT

# HEAD 커밋 객체에서 정본을 꺼낸다 — 작업트리 상태와 무관
export_src() {  # $1=rel → $WORK/src/<i>
  local rel=$1 out=$2
  mkdir -p "$out"
  git -C "$ROOT" archive --format=tar "$HEAD" -- "$rel" | tar -x -C "$out" || die 4 "git archive 실패: $rel"
  [ -f "$out/$rel/SKILL.md" ] || die 4 "커밋 $HEAD 에 정본 없음: $rel/SKILL.md"
}

# 디렉터리 트리 해시(상대경로+내용, 설치기록 .strict-* 제외). 실패·빈값은 exit 4.
tree_hash() {
  local d=$1 h
  if [ ! -d "$d" ]; then echo "-"; return 0; fi
  case "$d" in *.strict-staging-*) ! fault hash:stage || return 1 ;; esac
  h=$(set -o pipefail; cd "$d" && find . -type f ! -name '.strict-*' ! -name '.DS_Store' -print0 | LC_ALL=C sort -z |
      while IFS= read -r -d '' f; do printf '%s\0' "$f"; shasum -a 256 < "$f" || exit 1; done | shasum -a 256) \
    || die 4 "해시 계산 실패: $d"
  h=${h:0:16}
  [[ "$h" =~ ^[0-9a-f]{16}$ ]] || die 4 "해시 형식 이상('$h'): $d"
  echo "$h"
}

# 해시를 현재 셸에서 검증해 전역 HASH 에 담는다 — 명령 치환 안의 exit 가 무시되는 문제(V1 2차 #4) 방지
hash_of() {
  local out
  out=$(tree_hash "$1") || die 4 "해시 계산 실패: $1"
  [[ "$out" =~ ^([0-9a-f]{16}|-)$ ]] || die 4 "해시 형식 이상('$out'): $1"
  HASH=$out
}

SRC=()
for i in 0 1; do export_src "${REL[$i]}" "$WORK/src$i"; SRC+=("$WORK/src$i/${REL[$i]}"); done

report() {
  local drift=0 i sh dh state l
  for i in 0 1; do
    hash_of "${SRC[$i]}"; sh=$HASH
    hash_of "${DST[$i]}"; dh=$HASH
    [ "$sh" != "-" ] || die 4 "정본 해시 없음"
    if [ "$dh" = "-" ]; then state=MISSING; drift=1
    elif [ "$sh" = "$dh" ]; then state=OK
    else state=DRIFT; drift=1; fi
    echo "${ENGINE[$i]}  $state  src=$sh  dest=$dh  (${DST[$i]})"
  done
  for l in "${LEGACY[@]}"; do
    if [ -e "$l" ] || [ -L "$l" ]; then echo "LEGACY  present  $l  (폐지된 st 별칭 — --install --remove-legacy 로 백업 이동)"; drift=1; fi
  done
  return $drift
}

if [ "$MODE" = check ]; then
  echo "strict sync --check  (정본 commit ${HEAD:0:7})"
  rc=0; report || rc=$?
  [ $rc -le 1 ] || exit $rc
  if [ $rc = 0 ]; then echo "드리프트 0"; else echo "드리프트 있음"; fi
  exit $rc
fi

# ---------- install: 승인(병합)된 리비전에서만 ----------
MAIN=$(git -C "$ROOT" rev-parse -q --verify refs/remotes/origin/main || true)
[ -n "$MAIN" ] || die 3 "거부: origin/main 참조 없음 — git fetch 후 병합된 main에서 실행하세요"
[ "$HEAD" = "$MAIN" ] || die 3 "거부: HEAD($HEAD)가 origin/main($MAIN)이 아님 — PR 병합 후 main에서만 설치합니다"
# 추적 파일 수정은 거부(사람이 '내 수정이 설치된다'고 착각하는 것 방지). untracked·ignored 파일은
# 설치 내용에 들어갈 수 없으므로(커밋 객체에서 archive) 거부하지 않는다.
ST=$(git -C "$ROOT" status --porcelain --untracked-files=no -- "${REL[@]}" tools/sync-strict-skill.sh) \
  || die 3 "거부: git status 실패"
[ -z "$ST" ] || die 3 "거부: 정본 경로의 추적 파일에 미커밋 수정이 있음 — 커밋·병합된 내용만 설치합니다"$'\n'"$ST"

mkdir -p "$CLAUDE_HOME" 2>/dev/null || die 5 "설치 실패: $CLAUDE_HOME 생성 불가"
mkdir "$CLAUDE_HOME/.strict-sync.lock" 2>/dev/null || die 3 "거부: 다른 설치가 진행 중(락 $CLAUDE_HOME/.strict-sync.lock)"
LOCK="$CLAUDE_HOME/.strict-sync.lock"

ID="$(date -u +%Y%m%dT%H%M%SZ)-$$-$RANDOM"
echo "strict sync --install  commit $HEAD  (id $ID)"
echo "[before]"; report || [ $? = 1 ] || exit 4

# 1) 준비: 두 대상 모두 스테이징·검증 (여기서 실패하면 아무것도 바뀌지 않는다)
for i in 0 1; do
  parent=$(dirname "${DST[$i]}")
  mkdir -p "$parent" 2>/dev/null || die 5 "설치 실패(변경 없음): ${ENGINE[$i]} 대상 상위 $parent 준비 불가"
  stg=$(mktemp -d "$parent/.strict-staging-XXXXXX" 2>/dev/null) || die 5 "설치 실패(변경 없음): ${ENGINE[$i]} 스테이징 불가"
  STAGE+=("$stg")
  cp -R "${SRC[$i]}/." "$stg/" || die 5 "설치 실패(변경 없음): ${ENGINE[$i]} 복사 실패"
  hash_of "${SRC[$i]}"; src_h=$HASH
  hash_of "$stg"; stg_h=$HASH
  [ "$src_h" != "-" ] && [ "$src_h" = "$stg_h" ] || die 5 "설치 실패(변경 없음): ${ENGINE[$i]} 스테이징 해시 불일치"
  printf '{"commit":"%s","tree_hash":"%s","install_id":"%s","engine":"%s"}\n' \
    "$HEAD" "$src_h" "$ID" "${ENGINE[$i]}" > "$stg/.strict-install.json" || die 5 "설치 실패(변경 없음): 설치 기록 쓰기 실패"
done

# 2) 교체: errexit 를 끄고 모든 단계를 직접 검사한다. 실패·신호 시 이미 바꾼 대상을 전부 되돌리고,
#    되돌리지 못한 대상은 백업 위치와 함께 명시한다(V1 2차 #3).
DONE=()          # "i|backup_or_-"
UNRECOVERED=()
restore_one() {  # $1=i $2=backup_or_-  — 실제 디스크 상태를 보고 복원. 실패해도 다른 대상 복원은 계속.
  local i=$1 b=$2 dst=${DST[$1]}
  if fault "restore:$i"; then UNRECOVERED+=("${ENGINE[$i]}: $dst (백업 $b)"); return 0; fi
  if [ "$b" != "-" ] && { [ -e "$b" ] || [ -L "$b" ]; }; then
    # 백업이 존재 = 원본이 옮겨졌다 → 목적지에 무엇이 있든(새 설치본 또는 없음) 백업으로 되돌린다
    if [ -e "$dst" ] || [ -L "$dst" ]; then
      rm -rf "$dst" || { UNRECOVERED+=("${ENGINE[$i]}: $dst 제거 실패 (백업 $b)"); return 0; }
    fi
    mv "$b" "$dst" || { UNRECOVERED+=("${ENGINE[$i]}: $dst 복원 실패 (백업 $b)"); return 0; }
    echo "rollback  ${ENGINE[$i]}  백업에서 복원" >&2
  elif [ "$b" = "-" ] && [ -f "$dst/.strict-install.json" ] && grep -q "\"install_id\":\"$ID\"" "$dst/.strict-install.json"; then
    # 원본이 없던 대상에 이번 설치본이 들어갔다 → 제거해 원상(부재)으로
    rm -rf "$dst" || { UNRECOVERED+=("${ENGINE[$i]}: $dst 이번 설치본 제거 실패"); return 0; }
    echo "rollback  ${ENGINE[$i]}  이번 설치본 제거" >&2
  fi
  # 그 외: 백업 이동 전에 중단됨 → 원본이 제자리에 그대로 있음(변경 없음)
}
rollback_all() {
  local entry
  for entry in "${DONE[@]+"${DONE[@]}"}"; do restore_one "${entry%%|*}" "${entry#*|}"; done
  DONE=()
}
fail_install() {  # $1=사유  $2=기본 exit
  rollback_all
  if [ ${#UNRECOVERED[@]} -gt 0 ]; then
    echo "오류: $1 — 복원 실패 대상(수동 복구 필요):" >&2
    printf '  - %s\n' "${UNRECOVERED[@]}" >&2
    exit 6
  fi
  echo "오류: $1 — 이미 교체한 대상은 복원함" >&2
  exit "$2"
}
on_signal() { trap - TERM INT HUP; fail_install "신호로 중단" 7; }
trap on_signal TERM INT HUP
set +e
for i in 0 1; do
  dst=${DST[$i]}; home=$(dirname "$(dirname "$dst")"); b="-"
  if [ -e "$dst" ] || [ -L "$dst" ]; then b="$home/.strict-backups/$ID/strict"; fi
  DONE+=("$i|$b")   # 이동 '전에' 등록 — 이후 어느 순간 신호가 와도 restore_one 이 실제 상태로 판단(V1 3차 #1)
  if [ "$b" != "-" ]; then
    mkdir -p "$(dirname "$b")" && mv "$dst" "$b" || fail_install "${ENGINE[$i]} 백업 이동 실패" 5
    if fault "sigterm-after-backup:$i"; then kill -TERM $$; sleep 1; fi
  fi
  if fault "activate:$i" || ! mv "${STAGE[$i]}" "$dst"; then
    fail_install "${ENGINE[$i]} 활성화 실패" 5
  fi
  [ "$b" = "-" ] || echo "backup  ${ENGINE[$i]}  $b"
  if fault "sigterm:$i"; then kill -TERM $$; sleep 1; fi
done
set -e
trap - TERM INT HUP

if [ "$REMOVE_LEGACY" = 1 ]; then
  for l in "${LEGACY[@]}"; do
    [ -e "$l" ] || [ -L "$l" ] || continue
    home=$(dirname "$(dirname "$l")")
    mkdir -p "$home/.strict-backups/$ID"
    mv "$l" "$home/.strict-backups/$ID/$(basename "$l")"
    echo "legacy  moved  $l → $home/.strict-backups/$ID/$(basename "$l")"
  done
fi
echo "[after]"
rc=0; report || rc=$?
if [ $rc = 0 ]; then echo "설치 완료 — 드리프트 0"; exit 0; fi
[ $rc -le 1 ] || exit $rc
echo "설치 후에도 드리프트(legacy 잔존 등) — 확인 필요" >&2; exit 1
