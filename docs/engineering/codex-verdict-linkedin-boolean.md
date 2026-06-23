# 독립 적대검증 판정 — linkedin-boolean-inject

VERDICT: PASS

검증일: 2026-06-24  
검증자: Claude Code (독립 2차 적대검증 역할, 구현자 아님)  
커밋: f360371 (RED) → 374c7a1 (GREEN)

---

## pytest 실행 결과 (실제 숫자)

```
512 passed, 5 subtests passed in 9.64s
```

신규 테스트 5개 모두 통과:
- test_ac1_counter_empty_boolean_query_falls_back PASSED
- test_ac1_counter_plain_channel_keeps_standard_keyword PASSED
- test_ac1_linkedin_session_yields_boolean_query PASSED
- test_ac1_public_web_also_uses_boolean_query PASSED
- test_ac2_prompt_excludes_years_region_for_boolean_channel PASSED

---

## 반증 시도 목록

### [1] 체인 추적 — keywords_for_item → execute_queue_item → run_keyword_search → _goto_search_surface 고아 경로

**시도**: `keywords_for_item`이 반환한 tuple이 `execute_queue_item` 내부에서 누락/변형되어
LinkedIn URL 생성 전에 사라지는 고아 경로가 있는지 소스를 전 구간 추적.

**추적 결과**:
- `keywords_for_item(item)` → `tuple[str, ...]` 반환
- `execute_queue_item`는 이 tuple을 그대로 `runner.run_keyword_search(keyword, ...)` 에 순차 전달
- `_goto_search_surface`(portal_worker.py)는 `linkedin_rps` 채널일 때 `searchKeyword={quote(keyword)}`로 URL 생성
- 중간 변형/누락 지점 없음. boolean_query 문자열은 trim 후 tuple에 저장되며 URL 인코딩만 적용됨

**결과: 깨뜨리기 실패 (고아 경로 없음)**

---

### [2] 드리프트 검사 — BOOLEAN_CHANNELS 단일 출처 및 public_web 누락 여부

**시도**: `BOOLEAN_CHANNELS`가 `models.py` 외의 다른 파일에 하드코딩되거나,
`public_web`을 누락한 독립 판정 코드가 남아 있는지 전체 codebase grep.

**grep 결과**:
```
models.py:12:BOOLEAN_CHANNELS: frozenset[Channel] = frozenset({"linkedin_rps", "public_web"})
llm_keywords.py:33:_BOOLEAN_CHANNELS: frozenset[Channel] = BOOLEAN_CHANNELS  # 별칭, 단일 출처 참조
llm_keywords.py:54:  if channel in _BOOLEAN_CHANNELS
llm_keywords.py:123: if channel in _BOOLEAN_CHANNELS
portal_queue_executor.py:36: if session.channel in BOOLEAN_CHANNELS
```

`models.py` 단일 선언, 나머지 두 파일은 import 참조. 하드코딩 독립 선언 없음.
`public_web`은 frozenset에 포함되어 있으며 누락 경로 없음.

**결과: 깨뜨리기 실패 (드리프트 없음)**

---

### [3] dedup·공백·순서·빈값 edge case — 0건 검색 또는 검색어 손상

**시도**: 런타임 probe 8종 직접 실행.

| probe | 입력 | 기대 | 실제 |
|---|---|---|---|
| AC1-1 | linkedin_rps + `(Python OR Django) AND Seoul` | boolean_query 그대로 | PASS |
| AC1-2 | saramin + boolean_query | standard_keyword 유지 | PASS |
| AC1-3 | linkedin_rps + `   ` (공백만) | standard_keyword 폴백 | PASS |
| AC1-4 | public_web + boolean_query | boolean_query 그대로 | PASS |
| AC1-5 | linkedin_rps + boolean_query 키 없음 | standard_keyword | PASS |
| AC1-6 | jobkorea + boolean_query | standard_keyword (평문 채널) | PASS |
| AC1-7 | linkedin_rps 세션 2개, 동일 boolean_query | dedup → 1개만 | PASS |
| AC1-8 | linkedin_rps + `''` + standard_keyword `''` | 빈 tuple (dropped) | PASS |

공백 trim(`strip()`) → 빈 문자열 → 폴백 경로 정상. dedup(seen 집합)이 중복 제거 정상.
0건 검색 유발 경로(빈 keyword) 는 tuple에서 제외되어 runner에 전달되지 않음.

**결과: 깨뜨리기 실패 (edge case 모두 정상)**

---

### [4] AC2 프롬프트 토톨로지 — 테스트가 구현을 베끼는지

**시도**: `test_ac2_prompt_excludes_years_region_for_boolean_channel` 테스트가
`_build_prompt()` 반환값을 expected로 재사용(토톨로지)하는지 확인.

**확인**:
- 테스트는 `_build_prompt(_FakePosition(), "linkedin_rps")`를 호출한 뒤
  `assertIn("연차", prompt)`, `assertIn("지역", prompt)` 로 부분 문자열을 독립 단언함
- expected 문자열을 구현에서 복사하지 않음 — 핵심 제외 개념("연차", "지역")을 독립 리터럴로 단언

**AC2 실제 프롬프트 제외 지시 확인**:
- `"연차·경력년수·지역·근무지·OTW(연봉/처우)는 boolean_query 에 절대 넣지 마라"` 포함 확인
- Title + Skill + Domain만 구성 지시 포함 확인
- 평문 채널(saramin 등)은 `'boolean_query 는 빈 문자열("")로 두어라.'` 지시 확인

**결과: 토톨로지 아님. 테스트는 독립 단언. AC2 프롬프트 요구사항 충족 확인**

---

## 결함 목록

없음.

---

## 종합

4개 반증 시도 모두 실패(= 구현이 주장을 충족). pytest 512 passed.

VERDICT: PASS
