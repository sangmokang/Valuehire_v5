#!/usr/bin/env bash
# Harness Engineering 자동 로더 (UserPromptSubmit hook)
# 목적: 코드 구현 의도가 감지되면, 사장님이 매번 타이핑하지 않아도
#       하니스 원칙(docs/harness-engineering.md)과 게이트 절차(docs/harness.md)를
#       자동으로 컨텍스트에 주입한다. SOT 불변식 5("내 코드는 안 믿는다 — 두 번 깐다").
#
# 이 장치가 필요한 이유: 안 믿어야 할 대상이 Claude 자신이므로,
# 규율을 Claude의 기억/약속이 아니라 하니스(hook)가 결정론적으로 강제한다.

set -euo pipefail

input="$(cat)"

# 사용자 프롬프트만 추출
prompt="$(printf '%s' "$input" | python3 -c 'import sys,json
try:
    print(json.load(sys.stdin).get("prompt",""))
except Exception:
    pass' 2>/dev/null || true)"

# 코드 구현 의도 키워드 (false-negative 비용 > false-positive 비용 → 넓게 잡는다)
if printf '%s' "$prompt" | grep -qiE '구현|만들|고쳐|고친|수정|버그|디버그|리팩|기능|함수|클래스|스크래퍼|스크래핑|스크립트|코드|테스트 ?작성|커밋|배포|implement|fix|refactor|bug|debug|feature|build a|add a|function|class|patch|작업 ?시작'; then

  ctx="$(cat <<'EOF'
[하니스 자동 로드 — 코드 작업 감지]
이 작업은 docs/harness.md(게이트 절차) + docs/harness-engineering.md(원칙)를 따른다.
사장님은 너의 코드를 믿지 않는다(SOT 불변식 5). 아래를 건너뛰지 마라:
  0.5 과거 회수 — memory/코드/스킬/문서 3축 grep. 있으면 새로 만들지 말고 재사용.
  1   스펙       — 인수 기준 1개(무엇이 참이면 끝). 못 적으면 너무 큼 → 쪼갠다.
  2   RED 먼저   — worktree(make task NAME=...)에서 실패 테스트부터 커밋(TDD).
  3   작은 단위  — 파일 1~5, diff 50~300줄. 큰 덩어리 금지. RED→GREEN 최소 변경.
  4a  기계검증   — ./verify.sh exit 0. 출력 숫자 그대로 보고. 통과 전 "완료" 금지.
  4b  2패스 적대검증 — 패스1: 스스로 깬다(빈값·경계·429·중복·secret).
                       패스2: codex:rescue 로 독립 2차검증. 둘 다 못 깨야 통과.
  5   배송       — make ship → PR. CI 초록 + merge 전까지 "완료" 없음.
앤트로픽 Building Effective Agents 정렬: 단순하게 · 투명하게(계획 노출) · 도구/검증 충분히 · 가드레일.
게이트를 못 넘으면 다음 단계로 가지 마라. 사장님께는 쉬운 한국어로 보고(SOT 0번).
EOF
)"

  python3 -c 'import json,sys
print(json.dumps({"hookSpecificOutput":{"hookEventName":"UserPromptSubmit","additionalContext":sys.argv[1]}}))' "$ctx"
fi

exit 0
