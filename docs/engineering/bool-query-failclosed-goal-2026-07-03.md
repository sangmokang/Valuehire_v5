# Goal — PC-K3 BUG-BOOL-FAILOPEN 봉인 (빈 boolean_query fail-closed) · 2026-07-03

> 모드: code-change · 위험등급 L3 (라이브 검색필터 주입 경로). 근거: addendum-2026-07-02 R13/PC-K3.

## 현재 상태 (직접 연 file:line)
- `tools/multi_position_sourcing/llm_keywords.py:158-165` — `inject_boolean_queries`: `if boolean_query:` else 세션을 **그대로 통과**(조용히 skip).
- `tools/multi_position_sourcing/llm_keywords.py:229-230` — `inject_channel_search_filters`: `if boolean_query:` — 빈 boolean_query면 `extra_by_channel`에 안 넣고 **조용히 skip**.
- 배선(고아 아님): `dry_run.py:111`가 `inject_channel_search_filters`를 호출(라이브 검색 드라이버).
- 두 함수 docstring이 스스로 불변식 선언("LLM 실패는 KeywordGenerationError 전파, 조용히 빈 채로 통과 금지") — 그런데 `generate_keyword_plan`이 **예외가 아니라 빈 문자열 boolean_query**를 반환하면 `if boolean_query:`가 조용히 삼켜 불변식 위반.
- 데이터 형상: `LLMKeywordPlan.keywords: tuple[str,...]` + `boolean_query: str=""` (llm_keywords.py:43-44). boolean 채널=`BOOLEAN_CHANNELS`(linkedin_rps/public_web).

## 근본 원인
boolean 채널은 boolean_query가 있어야 X-ray 검색이 된다. 유효 keywords가 있는데 boolean_query가 비면(''/'   ') 그 채널은 **빈 쿼리로 0건 검색** → 무인 검색이 "후보 없음"으로 오결론(selectors-ledger 교훈 위반). 현행은 예외만 전파하고 '빈 문자열 반환'은 조용히 통과.

## 계약 (SDD)
신규 가드 `_require_boolean_query(channel, plan) -> str`:
- `plan.keywords`(유효) 이고 `plan.boolean_query.strip()==""` → `KeywordGenerationError` raise (fail-closed).
- 그 외 → `plan.boolean_query` 반환(정상 경로 불변).
- `inject_boolean_queries`·`inject_channel_search_filters`의 boolean 채널 루프가 이 가드를 통과해서만 주입.
- 평문 채널(saramin/jobkorea)은 영향 0(boolean 루프 밖).

## 인수기준 (기계검증 1)
`tests/test_bool_query_failclosed.py` GREEN: boolean 채널 포함 세션에 (유효 keywords + 빈/공백 boolean_query) fake LLM을 주면 `inject_boolean_queries`·`inject_channel_search_filters` 둘 다 `KeywordGenerationError` raise. 정상 boolean_query면 raise 없이 `filters['boolean_query']` 주입(회귀). + `./verify.sh` exit 0.

## 적용 게이트
harness 0→1→2(RED)→3(GREEN)→4(verify)→4b(자기적대+Codex V1+Claude V2)→5(ship PR).

## 적대검증 정조준
- 평문 채널(saramin/jobkorea)의 정상 빈 boolean_query가 잘못 raise되지 않는가(격리).
- keywords도 빈 degenerate case에서 이중 raise/오동작.
- 기존 test_channel_search_filters·test_boolean_livewire 회귀.
- 공백만('  \t')·None boolean_query.

## 비범위
llm_keywords 다른 fail-open(있으면 별도), harvest async 버그(PC-K4).

## 적대 검증 로그
(비움 — 게이트4b에서 채움)
