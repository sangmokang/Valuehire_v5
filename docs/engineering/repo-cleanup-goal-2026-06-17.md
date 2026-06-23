# Goal — 저장소 작업공간 정리 (repo-cleanup)

> 작성 2026-06-17 · 모드 `/strict` · 이 문서는 게이트 1 스펙(구현 전 계획서)이다.
> 실제 변경은 게이트 0 통과 후 `make task NAME=...` 작업방에서만 한다(main 읽기 전용 · SOT).

## 한 줄 목표
저장소 루트에 흩어진 **고아 검색결과 파일 18개**를 한 폴더로 모아 루트를 깔끔히 하고, 추적 안 되는 대용량 캐시(`captures/`, `.playwright-mcp/`)를 `.gitignore`로 영구 제외한다. **단, 그 전에 게이트 0을 막고 있는 `salvage-home-wip`(미완성 실작업)을 먼저 끝내야 한다.**

## 현재 상태 (직접 확인한 증거)
- **게이트 0 막힘**: `make red-ledger` → `Error 1`, 미해결 RED `salvage-home-wip` 1건. (`.harness/red-ledger.tsv:21`)
  → harness 규칙(`docs/harness.md:11-13`)상 이 RED를 닫기 전엔 어떤 새 작업도 시작 불가.
- **`salvage-home-wip`는 쓰레기가 아니라 미완성 실작업**: main 대비 커밋 1개뿐인데 그게 계획서 1개(`docs/engineering/salvage-home-wip-goal-2026-06-17.md`, 64줄). 그 계획은 홈에서 미커밋으로 보존된 `home-wip-20260617`(커밋 `1093832`)의 **linkedin-login 스킬 + 참고문서 2개**를 정식 반영하려는 것. 아직 실행 전이라 RED. → **삭제 금지, 완료 대상.**
- **루트 고아 파일 18개**: 전부 git 추적(committed)이지만 `tools/ scripts/ docs/ tests/ Makefile verify.sh` 어디서도 **참조 0곳**(grep 확인). 검색 결과 산출물이 루트에 쌓인 것.
  - `.md` 14개: `bigvalue_head_of_sales_multisearch.md`, `bigvalue_head_of_sales_practical_seniority_rescreen.md`, `korean_consumer_growth_marketing_candidates.md`, `korean_marketing_candidate_leads.md`, `moorgen_space_sales_manager_search.md`, `spoonlabs_vigloo_content_billing_search.md`, `techfinratings_ai_ml_engineer_search_20260615.md`, `uglylab_cmo_ai_search_step5_handoff.md`, `uglylab_cmo_chatgpt_search_candidates.md`, `valuehire-ai-search-harness-engineering-prompt.md`, `wrtn_ai_search_results_2026-06-06.md`, `wrtn_global_brand_marketer_na_search_20260609.md`, `wrtn_kyarapu_jp_pm_search_86ew25gkz.md`, `(+ multisearch 결과 1)`
  - `.html` 4개: `valuehire-ai-search-harness-adversarial-review.html`, `valuehire-ai-search-harness-engineering-prompt.html`, `valuehire-local-browser-setup-guide.html`, `valuehire-windows-discord-search-setup-guide.html`
  - `.txt` 1개: `chatgpt_search_uglylab_cmo_result.txt`
  - **유지(정리 대상 아님)**: `CLAUDE.md`(SOT), `requirements-dev.txt`(러너 의존성, `docs/harness.md:9`에서 참조).
- **미추적 캐시**: `captures/`, `.playwright-mcp/` — `git status`에 `??`로 잡힘. `salvage-home-wip-goal:59`가 "영구 비범위(커밋 금지)"로 명시. 현재 `.gitignore`에 없음.
- **건드리면 안 되는 것**: 진행 중 작업방 3개(`intake-posting-url`, `vision-fallback-recovery`, `discord-position-briefing`) — 각각 미머지 커밋 1 + 미저장 변경 1.

## 근본 원인
- 검색 작업 산출물을 worktree/폴더 규칙 없이 루트에 직접 떨궈 누적됨.
- 캐시 디렉터리가 `.gitignore`에 없어 매번 미추적으로 노출됨.
- 홈에서 worktree 없이 작업(salvage 원인)해 미커밋이 쌓였고, 정식 반영(게이트) 전이라 RED가 남아 게이트 0을 막음.

## 인수 기준 (게이트 4에서 판정)

### Phase 0 — 게이트 0 해제 (선행 · 필수)
**기계 단언**
- P0-A1. `make red-ledger` exit 0 (미해결 RED 0).
- P0-A2. `salvage-home-wip-goal`의 인수기준(A1~A6)을 그 작업방에서 충족해 RED→GREEN으로 닫음. (= linkedin-login 스킬 + 참고문서 2개 + 새 계약테스트가 main에 반영되고 `./verify.sh` exit 0)

> 비고: Phase 0은 본 정리와 별개의 실작업이다. 본 문서는 "정리를 시작하려면 이게 선행"임을 못박는다. salvage를 끝낼지/접을지는 **사장님 결정 사항**(접으면 worktree+branch+ledger행 제거로도 게이트 0은 열리나, 실작업 유실).

### Phase 1 — 루트 정리 (게이트 0 통과 후)
**기계 단언 (`./verify.sh`로 검사)**
- P1-A1. 루트(`./*.md ./*.html ./*.txt`)에 검색결과 산출물 0개. (허용 잔존: `CLAUDE.md`, `requirements-dev.txt`)
- P1-A2. 18개 전부 `docs/search-results/` 아래에 존재하고, `git log --follow`로 이력 보존(= `git mv` 사용, 신규 추가 아님).
- P1-A3. 끊긴 참조 0: 이동 후 `grep -rIl <옮긴파일명> tools scripts docs tests` 결과가 기존과 동일(0곳이었으므로 0 유지).
- P1-A4. `.gitignore`에 `captures/`, `.playwright-mcp/` 추가되어 `git status`에 해당 디렉터리 미노출.
- P1-A5. **자기확장 규칙**: `tests/`에 "루트에 고아 결과파일이 다시 생기면 실패"하는 구조 단언 테스트 추가, GREEN.
- P1-A6. `./verify.sh` exit 0, 출력 숫자(`N passed`) 그대로 기록. 기존 테스트 회귀 0.

**판단 단언 (게이트 4b 독립 검증자)**
- P1-J1. `docs/search-results/`가 적절한 보존 위치인가(또는 추적 해제+`artifacts/`가 나은가) — 결과물을 계속 추적할 가치가 있는지 판정.
- P1-J2. 이동이 다른 작업방/외부 링크를 깨지 않는가(고아 판정이 진짜인가).

## 적용 Harness 게이트
- **0** — `make red-ledger` exit 0. **현재 막힘** → Phase 0 선행.
- **0.5** — 과거 지시 회수: 본 정리/아카이브 규칙이 기존에 있었는지 grep(메모리·코드·문서 3축). 본 문서가 그 회수 결과.
- **1** — `gh issue create`로 위 인수기준 등록(gh 막히면 ledger에 사유 기록 후 진행).
- **2** — `make task NAME=repo-cleanup`로 작업방 생성, P1-A1/A5를 실패시키는 RED 테스트 먼저 커밋.
- **3** — `git mv` 18개 + `.gitignore` 2줄 + 구조 테스트(RED→GREEN, 최소 diff).
- **4** — 4a `./verify.sh` exit 0 숫자 첨부 / 4b 분리 검증자 반증.
- **5** — `make ship`(verify 재실행→push→PR). CI 초록 + merge 전 완료 없음.
- **6** — merge 후 `git worktree remove` + `/clear`.

## codex 적대검증 항목 (게이트 5)
- 옮긴 18개가 정말 고아인가 — 빌드/문서/외부 스킬에서 상대경로로 참조하는 숨은 곳은 없나(내 grep이 놓친 경로).
- `git mv`가 이력을 진짜 보존했나(`--follow`로 확인), 신규 add로 둔갑하지 않았나.
- 구조 테스트(P1-A5)가 실제로 "루트 재오염"을 잡는가, 아니면 항상 통과하는 가짜 단언인가(빈 테스트 의심).
- `.gitignore` 추가가 이미 추적 중인 무언가를 의도치 않게 무시하지 않는가.

## SOT 체크리스트 (읽은 파일)
- `CLAUDE.md` — 0번 규칙(쉬운 한국어 보고)·불변식 5종·"main 직접 금지, 작업방에서, 검사 먼저".
- `docs/harness.md` — 게이트 0~6, 문서 RED=구조/참조 검사, 자기확장 규칙, 배관 명령(`make red-ledger/task/verify/ship`).
- `.harness/red-ledger.tsv` — 미해결 RED 1건(salvage-home-wip) 확인.
- `skills/multisearch/SKILL.md` — multisearch 산출물 위치 규칙 참고.
- 충돌 시 SOT 우선. LLM 호출은 `claude -p` 우선.

## 비범위 (이번에 안 함)
- 진행 중 작업방 3개(intake-posting-url / vision-fallback-recovery / discord-position-briefing) 손대기.
- `captures/`·`.playwright-mcp/` 내용물 커밋(영구 비범위 — `.gitignore`로 제외만).
- 검색결과 문서들의 내용 수정/요약/병합.
- salvage-home-wip의 실내용 구현(별 작업 — Phase 0으로 참조만).
- 데스크톱(`~/Desktop/Valuehire_v5`) 정리.

## 적대 검증 로그
(게이트 5 codex 판정 + 게이트 6 클로드 재적대검증을 본문 그대로 append. 원본 jsonl 경로 + agentId 포함.)
