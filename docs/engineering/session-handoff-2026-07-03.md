# 새 세션 핸드오프 프롬프트 (2026-07-03) — Valuehire 무인 헤드헌팅 이어가기

> 아래 코드블록을 **새 Claude Code 창에 그대로 붙여넣으면** 됩니다. fresh 세션은 이전 대화 기억이 없으므로 필요한 맥락·경로·규율을 모두 담았습니다.

---

```
/st 무인 헤드헌팅 파이프라인 이어서 진행한다. 아래 맥락을 먼저 흡수하고, 과거회수부터 한 뒤 착수해라.

# 저장소 / SOT (먼저 읽어라)
- 저장소: /Users/kangsangmo/Valuehire_v5 (main 브랜치, git)
- 최상위 규칙: CLAUDE.md (SOT 불변식 — 사장님께 쉬운 한국어, 3사 자동로그인 안 막음, 크롬 점유 시 양보·자동재개, 발송 자동금지, 내 코드 두 번 깐다)
- 표준 작업 루프/게이트: docs/harness.md
- 미해결 RED 장부: .harness/red-ledger.tsv  (착수 전 `make red-ledger` 로 clean 확인)
- 통합 설계도(SOT, 반드시 읽고 중복 회피):
  - docs/engineering/valuehire-pipeline-consolidation-spec-2026-07-01.md (44조각 백로그)
  - docs/engineering/valuehire-pipeline-consolidation-spec-addendum-2026-07-02.md (심화·매칭정밀도·개인화·완결감사)
  - docs/engineering/valuehire-pipeline-consolidation-backlog-2026-07-01.json

# 지금까지 완료(이번 주 병합됨 — 다시 하지 마라)
- PR#45 브랜치 정합(하드제외 코드 반영), #46 직무매칭 오탐 제거(keyword_in_text 단어경계),
  #49 빈 boolean_query fail-closed, #52 로그인게이트 세션락/authwall 감지, #53 harvest _resolve async 안전화.
- 하드제외 등록면(PC-C0/C1a1/C1a) 병합 완료.

# 핵심 상황(가장 중요) — 왜 다음이 막혀 있나
무인화의 "척추" P0 조각들(라이브 실행엔진 PC-D5, 크롬 점유 센서 배선 PC-F1/F2, 러너면 하드제외 PC-C3a,
경력과다 컷 PC-I1/I2, 상시 데몬 PC-K6)은 전부 humansearch_cdp_run.py(러너)·humansearch.py·scoring.py 를
건드려야 하는데, **지금 동시 세션 ~10개(task/humansearch-multipos·paginate·clickup-lane 등)가 그 파일들을
stale 브랜치로 편집 중**이라 착수하면 병합충돌 난다. `git worktree list` 로 확인해라.

# 그래서 다음 순서(권고)
1. **교통정리 먼저(최대 레버):** stale 미병합 브랜치들을 git 으로 전수 점검(`git worktree list`,
   `git log main..<branch> --oneline`, `git rev-list --left-right --count main...<branch>`).
   고유커밋 0(완전병합)인 건 삭제, 고유커밋 있는 건 살베지/병합/종료 결정. 특히 humansearch_cdp_run.py·
   humansearch.py 를 무는 stale 브랜치(multipos 등)를 정리해야 척추 착수가 열린다. 이건 사장님 확인받고 진행.
2. **교통정리 후 척추 착수(addendum §3 순서):** PC-D5(라이브 실행자 어댑터) → PC-F1(owner_activity.py 를
   task/ai-search-pipeline-wip 에서 살베지해 compute_yield_decision 순수계약) → PC-E1(봇방지 페이싱) →
   PC-C3a(러너면 하드제외) + PC-I1/I2(졸업연도 경력상한 컷) → PC-K6(데몬 크래시루프 수리).
3. 지금 당장 충돌 없이 할 수 있는 소품(가치 낮음): PC-E1 페이싱 primitive(단, 소비자 미배선이라 고아 주의).

# 작업 규율(반드시)
- 한 조각 = 한 worktree = 인수기준 1개. `make task NAME=<slug>` 로 worktree(../Valuehire_v5-<slug>) 생성.
- RED 먼저 커밋 → 최소변경 GREEN → `./verify.sh`(pytest 전체, exit 0, 숫자 그대로 보고).
- 게이트4b 적대검증: 내가 먼저 mutation 으로 깨고 → Codex(/codex:rescue, V1) → 리셋 Claude 서브에이전트(V2).
  각 조각 docs/engineering/<slug>.verdict.json 에 G/V1/V2/T 증거 기록. 셋 다 통과 전엔 "됐다" 없음.
- 배송: `git push` → `gh pr create --base main` → CI 초록 확인 → `gh pr merge <n> --squash` →
  .harness/red-ledger.tsv 해당행 RED→GREEN(PR#·verify 숫자·4b 증거) → `git worktree remove` → 브랜치 삭제.
- 고아 금지(R4): 새 코드는 프로덕션 진입점→새코드 호출부를 grep 으로 증명. 안 불리면 완료 아님.

# 환경 함정(시간 아껴라)
- worktree 에서 테스트: 메인 venv 를 쓰되 import 가 worktree 를 보게 해야 한다:
  `PYTHONSAFEPATH=1 PYTHONPATH=<worktree경로> /Users/kangsangmo/Valuehire_v5/.venv-playwright/bin/python -m pytest <worktree>/tests/ -q`
  (cwd 가 메인이면 import 가 메인을 잡는다. PYTHONSAFEPATH 로 cwd '' 를 빼야 worktree 우선.)
- 로그인된 포털 크롬(포트 9222)은 절대 kill/stop 금지(3사 로그인 세션). 자동화 브라우저(playwright-mcp)만 정리 가능.
- 개발 중엔 관련 test 파일만 돌려 브라우저 테스트 안 띄우고, 최종 verify 때만 전체.
- Codex(/codex:rescue)는 종종 "대기 중"/placeholder 만 반환한다. 실제 판정 본문은 transcript jsonl
  (subagents/agent-<agentId>.jsonl 또는 tasks/<agentId>.output)에서 필터링해 확보해라. 빈 응답=통과 아님.

# 검증 명령(가정 말고 실행)
- 전체검사: `./verify.sh` (현재 baseline 829 passed, 3 xfailed).
- 게이트0: `make red-ledger`.  worktree: `make task NAME=<slug>`.

먼저 위 SOT 문서들 읽고 `git worktree list` + `make red-ledger` 상태 확인한 뒤, 1번(교통정리) 범위를
사장님께 쉬운 한국어로 제안하고 승인받아 시작해라. 코드 손대는 모든 작업은 worktree 에서, 두 번 깐다.
```

---

## 붙여넣기 팁
- 위 코드블록 전체를 복사해 새 창 첫 메시지로 붙여넣으세요.
- `/st` 로 시작하니 새 세션도 같은 적대검증 규율로 돕니다.
- 새 세션이 제일 먼저 `git worktree list` 로 동시 세션 stale 브랜치를 보고, **교통정리부터** 제안할 겁니다(그게 척추를 여는 열쇠).
