# Valuehire AI Search — 구현 상태 브리핑

> ClickUp 포지션 → 후보 소싱 → 점수화 → handoff 파이프라인의 현재 구현 현황
> 레포 `/Users/kangsangmo/Valuehire_v5` · 브랜치 `main` · 최신 커밋 `a09cfd1` · 작성일 2026-06-17

**상태 요약:** Reservoir 모델 GREEN · 포털 안정성 GREEN · verify 464 passed · **RED 1건(salvage-home-wip)** · 검색 필터 정교화 미착수

| verify passed | GREEN 작업(#1~#26) | 미해결 RED | 활성 worktree |
|:---:|:---:|:---:|:---:|
| **464** | **13** | **1** | **4** |

---

## 1. 전체 아키텍처

AI Search는 **"ClickUp 포지션 → 후보 소싱 → 점수화 → handoff"** 파이프라인이며 4개 층으로 구성된다.

| 층 | 구현체 | 역할 |
|---|---|---|
| **스킬 / 판단 로직** | `skills/search/`, `skills/multisearch/`, `skills/position-registration/` | LLM이 따르는 절차 명세. v4 레거시 코드 비의존, 독립 판단 로직 |
| **포털 소싱 엔진** | `tools/multi_position_sourcing/*.py` (40+ 모듈) | 사람인·잡코리아·LinkedIn RPS 실제 검색/수집/운영 안정성 |
| **저수지(Reservoir) 모델** | `embed.py`, `match.py`, `scoring.py`, `segments.py`, `harvest_*.py`, `reservoir_log.py`, `ab_harness.py` | 임베딩·세그먼트·재랭킹·A/B 측정 |
| **진입 / 배관** | `scripts/run_portal_search.py`, Discord 라우팅, Harness(`Makefile`/`verify.sh`) | 실행 진입점 + 재현성 게이트 |

**실행 경계 (SOT)**
- single 포지션 = `search` 스킬, multi 포지션 = `multisearch` 스킬
- 포털 자동복구(재로그인 / 타임아웃 / 셀렉터 드리프트 / 크롬 잔재 정리)는 `multisearch`가 담당
- 기본값은 **dry-run / read-only**. 실쓰기·발송은 사장님 승인 + 환경 게이트 필요
- **캡차 / 2FA / IP보안 챌린지 자동 우회 금지** — 막히면 멈추고 사람이 해결
- 실후보만 다룬다(placeholder/demo/fake 금지), 후보 자동 발송 금지

---

## 2. 모듈별 상태

### ✅ 구현 완료 — Reservoir 모델 (#1~#14)

| 모듈 | 역할 | 상태 |
|---|---|---|
| `segments.py` | 세그먼트 분류(명명 4 + unknown), 결정론 매핑 | GREEN #5 |
| `harvest_policy / runner / reservoir_log` | harvest 큐(12필드 계약 · 3머신 · 무조건 저장) | GREEN #7 |
| `scoring.py` | 품질 4기준(대학·직무·회사·이직안정성), EmploymentTenure | GREEN #8 |
| `embed.py` · `embeddings.sql` | 결정론 순수파이썬 임베더 · cosine · dedup · pgvector HNSW(멱등) | GREEN #10 |
| `match.py` | 세그먼트 필터 · 코사인 top-K · scoring 재랭킹 · url 타이브레이크 | GREEN #13 |
| `ab_harness.py` | 블라인드 A/B 배치 · 순도 리포트(candidate_id 누설 차단) | GREEN #14 |

### ✅ 구현 완료 — 포털 운영 안정성 (#18~#26)

| 모듈 | 역할 | 상태 |
|---|---|---|
| `portal_recovery.py` | 재로그인 지수 백오프(예외만 재시도, 보안챌린지 1회 정지) | GREEN #18 |
| `portal_worker.py` | 검색 시간제한(기본 60s, `asyncio.wait_for`) | GREEN #20 |
| `portal_autologin.py` | 로그인 셀렉터 드리프트 / missing_roles 감지 | GREEN #22 |
| 프로필 싱글톤 락 정리 | `clear_stale_singleton_locks`(고정 허용목록, 데이터 보존) | GREEN #24 |
| `search` · `multisearch` 계약 | 운영 안정성(자동 복구) 반영 + 계약 테스트 | GREEN #26 |

### ✅ 포지션 등록 / 추출
`position_registration.py` · `position_dedup.py` · `posting_extractor.py` · `posting_recognizer.py` — 구현 및 테스트 완료.

### ⚠️ 부분 구현 / 다음 작업 (goal-prompt 존재, 미착수)

> **검색 필터 정교화** (`search-filter-precision-goal-prompt.md`) — 현재 구현은 **키워드 1개만 입력**하고 연차·학력·지역·업종 facet을 적용하지 않으며, 결과카드 셀렉터가 라이브 DOM과 **일부 불일치**. AND/OR/NOT 키워드를 매 검색마다 초기화 후 한·영 동의어로 재세팅하는 로직 필요. **(최대 미완 영역)**

- LinkedIn 1촌 성장 / 멀티디바이스 운영(2026-06-15 문서) — 설계 단계
- 이슈 **#27**: search 스킬 line150 LinkedIn 기술 불일치(분리되어 미해결) — open

---

## 3. 테스트 · 검증

**verify 464 passed** (최근 search-skill-stability 기준), 누적 GREEN 유지.

```
tests/
  test_reservoir_{ab,doc,embeddings,harvest,match,scoring,segments}.py
  test_multi_position_sourcing.py
  test_portal_preflight_autologin.py
  test_search_skill_stability.py
  test_posting_{extractor,recognizer}.py
  test_position_{dedup,registration}.py
```

> **Red-Ledger:** 핵심 작업은 전부 GREEN. 유일한 RED = `salvage-home-wip` (worktree `../Valuehire_v5-salvage-home-wip`, 미완 작업). Harness 규칙상 **RED가 있으면 신규 작업 시작 금지** → 이것부터 닫아야 한다.

---

## 4. Harness 방법론

"출력 변동성을 줄여 재현 가능하게" — 모든 변경(코드·스킬·문서)이 게이트를 통과한다.

```
게이트0   시작 자격 (미해결 RED 없음 · 깨끗한 컨텍스트)
   ↓
게이트0.5 과거 지시 회수 (메모리·기존코드·스킬 3축 검색 → 중복 방지)
   ↓
게이트1   이슈 + 인수기준 (기계 단언 / 판단 단언 분리)
   ↓
게이트2   RED 먼저 — main 읽기전용, make task NAME=... worktree에서 시작
   ↓
   ...    구현 → GREEN
   ↓
게이트4b  독립 적대검증 (4~6 렌즈, refuted=false)
   ↓
verify.sh 전체 통과 → merge
```

배관은 `Makefile` + `verify.sh` + `scripts/harness/*` + pre-push 훅 + `.github/workflows/verify.yml`로 구현. 최초 1회 `make install-hooks`.

---

## 5. 리스크 · 오픈 이슈

1. **salvage-home-wip RED 미해결** — Harness 규칙상 다른 신규 작업을 막는 차단 항목.
2. **검색 필터 정교화 미착수** — 실제 검색 품질의 핵심인데 키워드 1개 / facet 미적용 상태. 셀렉터 DOM 드리프트 상존.
3. **미커밋 변경분** — `captures/`, `docs/engineering/`, `.playwright-mcp/`가 untracked.
4. **4개 활성 worktree 병렬 진행** — discord-position-briefing · intake-posting-url · salvage-home-wip · vision-fallback-recovery.

---

*근거: `.harness/red-ledger.tsv`, `git log`, `skills/{search,multisearch}/SKILL.md`, `docs/harness.md`, `docs/ai-search/*` · 2026-06-17*
