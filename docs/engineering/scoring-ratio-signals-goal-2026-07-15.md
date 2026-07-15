# Goal — scoring.py 학력·회사·대학 점수 비율화 (2026-07-15)

## 현재 상태 증거

- `tools/multi_position_sourcing/scoring.py:226-234`: 학력 문자열이 비어 있지 않아도 영문 토큰
  (`bs/ba/bachelor/master/ms/phd/computer`)이 없으면 5점이며, 한국어 학위 표기는 만점 신호가 아니다.
- `tools/multi_position_sourcing/scoring.py:133-137`: 대학 티어는 별칭 하나가 맞으면 8점,
  아니면 학력 근거가 있어도 0점이다.
- `tools/multi_position_sourcing/scoring.py:183-191`: 회사 티어는 별칭 하나가 맞으면 10점,
  회사 이력만 있으면 6점, 이력 없으면 0점인 고정 분기다.
- v4 `src/lib/b2c/opportunityMatchScorer.ts:143-155,293-299`: 각 축을
  `weight * matched / total`로 계산한다. 단, v4의 `total == 0 -> 1`과 한글을 제거하는
  정규화(`:301-303`)는 후보 근거 결손·한국어 입력에 부적합하므로 가져오지 않는다.
- `docs/sot/24-position-jd-sot.json:10-14`: 점수 밴드는 strong `85+`, candidate `70-84`,
  drop `<70`이다.
- 기존 사례: 있음. `docs/prompts/humansearch-scoring-recalibration-goal-2026-07-15.md:23-34`의
  한국어 학위 만점·전문학사 제외·커트라인 유지 결정을 재사용한다.

## 근본 원인

세 축이 “근거 존재”와 “긍정 신호 확인”을 별도 요건으로 세지 않고 하나의 substring 분기로
합쳐 평가한다. 그래서 별칭 하나가 전체 점수를 좌우하고, 한국어 학위처럼 의미는 같지만 문구가
다른 근거가 과소평가된다. 별칭 사전 자체를 분모로 쓰면 별칭을 추가할수록 같은 후보 점수가
내려가므로 v4의 `total` 의미(평가 요건 수)와도 맞지 않는다.

## 단일 인수 기준

`education`, `company_tier`, `university_tier` 각각이 아래 두 논리 요건의
`matched / total(=2) * 기존 최대점수`로 계산되고, 한국어 학위 표기 회귀와 운영 호출 경로가
focused test 및 전체 `verify.sh`에서 모두 통과하면 끝난다.

1. 근거가 존재한다.
2. 해당 축의 긍정 신호가 확인된다.

따라서 점수 계약은 다음과 같다.

| 축 | 근거 없음 | 근거만 있음 | 긍정 신호 있음 | 최대점수 |
|---|---:|---:|---:|---:|
| education | 0 | 5 | 10 | 10 |
| company_tier | 0 | 5 | 10 | 10 |
| university_tier | 0 | 4 | 8 | 8 |

동의어 여러 개가 한 번에 잡혀도 “긍정 신호” 한 요건만 충족한다. 별칭 개수는 분모가 아니다.
한국어 긍정 학위 신호에는 `학사`, `석사`, `박사`, `대학교 졸업`, `대학 졸업`, `4년제 졸업`,
`대졸`, `공학사`, `이학사`를 포함하고 `전문학사` 단독 표기는 만점 신호에서 제외한다.

## 입출력 계약

- 입력: 기존 `CapturedProfile` (`education: str`, `current_or_past_companies: tuple[str, ...]`).
- 내부 함수:
  - 비율 계산: 정수 `matched`, `total`, `weight` → `0..weight` 정수.
  - 학력/회사/대학 축: `CapturedProfile` → `(score: int, reasons: tuple[str, ...])`.
- 출력: 기존 `score_profile_for_position(profile, position) -> PositionMatch` 시그니처와
  `score_breakdown` 키를 유지한다.
- 상태 전이: 입력 프로필 → 세 축의 요건별 매칭 수 → 비율 점수 → 기존 breakdown 합산·0~100 clamp.
- 최대점수(10/10/8)와 SOT24 85/70 밴드는 바꾸지 않는다.

## 회귀 테스트 계약 (RED 먼저)

- `OO대학교 학사`, `OO대학교 석사`, `OO대학교 박사`, `OO대학교 졸업`은 education 10점.
- `OO전문대학 전문학사`는 학력 근거 5점만 받고 학위 긍정 신호로 만점 처리되지 않는다.
- 근거 없음/근거만/긍정 신호의 세 단계가 각 축에서 위 표의 점수를 낸다.
- 별칭을 여러 개 포함해도 최대점수를 넘지 않으며, 빈 입력은 v4와 달리 만점이 아니라 0점이다.
- `score_profile_for_position`의 breakdown이 새 학력 함수를 실제 호출한다.

## 비범위

- SOT24의 85/70 점수 밴드, 자동발송 게이트, 하드제외 정책 변경.
- must-have·연차·산업 배점 재분배, 중간 대학 티어 추가.
- 별도 `humansearch.score_humansearch` 채점식 변경.
- 운영 데이터 쓰기, 외부 발송, 배포, GitHub 이슈/PR 생성.

## 검증 명령

```bash
/Volumes/SSD/valuehire_v5/.venv/bin/python -m pytest tests/test_reservoir_scoring.py -q
./verify.sh
git diff --check
rg -n "_education_score|_company_tier_score|_university_tier_score|score_profile_for_position" \
  tools/multi_position_sourcing tests/test_reservoir_scoring.py
```

`package.json`에는 `strict:gate`가 없으므로 별도 strict gate 명령은 없다.

## SOT 체크리스트

- [x] `CLAUDE.md`, `docs/harness.md`, `docs/harness-engineering.md`,
  `docs/sot/24-position-jd-sot.json`, `Makefile`, `verify.sh`, `package.json` 읽음.
- [x] memory·기존 코드/git log·스킬/문서의 과거 지시 3축 회수.
- [x] 별도 worktree `task/scoring-ratio-signals` 사용.
- [x] RED focused test 실패 증거: `11 failed, 14 passed` 후 엣지 보강 `16 failed, 15 passed`.
- [x] GREEN focused `23 passed, 88 subtests`; 최신 main 재배치 후 전체 verify `1501 passed, 4 xfailed, 102 subtests`.
- [x] `score_profile_for_position` → `top_matches_for_profile`/reservoir scorer → dry-run 호출 경로 추적.
- [x] 자기 적대검증 + 독립 Codex + 외부 Claude 최종 PASS; verdict 산출물 기록.
