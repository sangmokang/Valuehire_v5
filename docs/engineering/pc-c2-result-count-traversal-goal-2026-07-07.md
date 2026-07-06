# PC-C2 — 전수조사 결과수 판단 트리(순수함수, 채널별 밴드) · 구현 킥오프/증거

> 상태: **GREEN(구현 완료, 적대검증 진행).** worktree `task/humansearch-result-count-tree`.
> 한 조각 = 한 worktree = 인수기준 1개.

---

## /st PC-C2(결과수 판단 트리) — code-change · L3

### 저장소 / SOT
- 저장소 `/Users/kangsangmo/Valuehire_v5` (main). 규칙 `CLAUDE.md`, 루프 `docs/harness.md`, 장부 `.harness/red-ledger.tsv`.
- 백로그 정의 `docs/engineering/valuehire-pipeline-consolidation-backlog-2026-07-01.json` **PC-C2** — `requirement_ids:[R7]`, `depends_on:[]`, worktree `task/humansearch-result-count-tree`.
- SOT 데이터 출처 `docs/sot/22-talent-search-filters.json` → `channels[<ch>].result_count_decision_tree`.

### 위험등급 · 모드
- **code-change · L3** (라이브 전수 순회 정책의 단일출처 결정함수 · SOT5). 순수함수라 **기계검증 100%**(수동 verdict 불필요).
- 풀하네스: worktree → RED→GREEN → G(뮤테이션) → V1(Codex)+V2(리셋 Claude) 병렬 → `pc-c2-result-count-traversal.verdict.json` 3자.

### 현재 상태 (직접 연 file:line)
- `docs/sot/22-talent-search-filters.json` `channels.saramin.result_count_decision_tree` = `0_to_4`(포기)·`5_to_80`(GOLD 전수)·`81_to_300`(상위40)·`300_plus`(AND추가). jobkorea 동일. `channels.linkedin.result_count_decision_tree` = `0_to_4`·`5_to_60`(전수)·`61_to_200`(상위20)·`200_plus`(조건추가).
- `tools/multi_position_sourcing/harvest_policy.py:58` `_SOT22_PATH` + `json.loads(read_text)` = SOT22 읽기 선례(재사용).
- 착수 전 `humansearch.py` 에 `plan_result_count_traversal`·`TraversalPlan` **부재**(grep 0건) → RED.

### 근본 원인
PC-C3b(라이브 전수 순회)가 "결과수 → 전수/부분/포기" 를 결정할 단일출처 순수함수가 없다. 채널마다 임계가 다른데(사람인/잡코리아 80 vs RPS 60), 이를 하드코딩하면 SOT22 와 이중정의되어 드리프트한다.

### 계약 (SDD)
```python
@dataclass(frozen=True)
class TraversalPlan:
    action: str        # "abort" | "full" | "top_n" | "add_condition"
    limit: int | None  # top_n → N(40/20), 그 외 None
    band: str          # 매칭된 SOT22 밴드 키
    channel: str

def plan_result_count_traversal(channel: str, result_count: int) -> TraversalPlan
```
- 밴드 경계·상한 N 은 **SOT22 채널별 트리에서 읽는다**(하드코딩 금지, SOT5).
- 밴드 키 파싱: `A_to_B`=[A,B], `N_plus`=[N,∞). 메타 키(`_source`·`read_via`·`note`) 무시.
- 서술→action: `상위 N`→top_n(N) · `추가`→add_condition · `전수`→full · `포기`→abort (이 순서 — 300_plus 가 '추가'와 '포기'를 둘 다 담아 순서가 중요).
- 경계 중첩([81,300]과 [300,∞))은 lo 오름차순 첫 매칭 → 낮은 lo 우선(결정론).
- fail-closed: 미지원 채널·음수·해석불가 밴드 → `ValueError`.

### 인수 기준 (기계 단언 — `tests/test_result_count_traversal.py`, 38 케이스)
1. 0~4 abort(전 채널), 전수 경계(사람인/잡코리아 5·80 / RPS 5·60) full.
2. ⭐ SOT5: 사람인/잡코리아 61·70·80 = full(RPS 60 상한 복사 금지).
3. top_n(사람인/잡코리아 81~300→40, RPS 61~200→20), add_condition(301+/201+).
4. off-by-one 경계(4/5, 80/81, 300/301 · 4/5, 60/61, 200/201).
5. fail-closed: 미지원 채널·음수 → ValueError.
6. SOT22 실조회: 트리 monkeypatch 로 밴드 바꾸면 결정도 바뀜(하드코딩 뮤턴트 차단).
7. `./verify.sh` exit 0.

### 적대검증 정조준
- 하드코딩 뮤턴트 생존(SOT 미조회) → monkeypatch 테스트로 차단.
- 300_plus '포기' 서술을 abort 로 오분류 → 서술해석 순서로 방어.
- 경계 off-by-one(≤ vs <) → 경계 테스트로 차단.
- RPS 임계를 전 채널 복사 → 사람인 61~80 full 단언으로 차단.
- 고아: 이 조각은 **staged seam** — 소비자는 PC-C3b(라이브 전수 순회). C3b goal 문서에 소비 배선 명시. C2 자체는 순수함수(프로덕션 라이브 배선은 C3b 몫, 비범위).

### 비범위
- 라이브 순회 루프 배선(PC-C3b: cards[:max_profiles] 하드캡 제거 + &start 다중페이지 + 이 결정 소비).
- SOT22 트리 내용 개정(있는 값을 읽을 뿐, 정책 변경 아님).

### ⛔ 안전 (SOT)
- 순수함수 — 브라우저/발송/로그인 무접촉. SOT1/2/3 직접 위반 없음.
- SOT5: 임계를 SOT22 단일출처에서 읽어 이중정의 방지.
- SOT2(봇금지)·전수 라이브 순회 페이싱은 소비자 C3b 가 PC-E1 재사용으로 책임(비범위).

### 환경 함정
- 검사 인터프리터 `/Users/kangsangmo/Valuehire_v5/.venv/bin/python`(websocket 보유). worktree 실행: `PYTHONSAFEPATH=1 PYTHONPATH=<worktree> .../.venv/bin/python -m pytest <worktree>/tests/ -q`. baseline main 977 passed.
- Codex: 뮤테이션은 `/private/tmp` 복사본에서. transcript jsonl 본문 확보.

### 적용 게이트
harness 0~6 + gate4b: G(뮤테이션 3종 caught) → V1(Codex)+V2(리셋 Claude) 병렬 → verdict.json 3자.

## 적대 검증 로그
`docs/engineering/pc-c2-result-count-traversal.verdict.json` 에 G/V1/V2/T 축적.
