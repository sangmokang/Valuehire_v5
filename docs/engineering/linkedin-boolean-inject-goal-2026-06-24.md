# goal — LinkedIn 검색창에 Boolean 검색식 실제 주입 (구멍 막기)

- 작성일: 2026-06-24
- 작업방: `worktrees` = `../Valuehire_v5-linkedin-boolean-inject`, 브랜치 `task/linkedin-boolean-inject`
- 모드: code-change · 위험 L3 (라이브 AI Search 파이프라인 동작 변경)
- 사장님 지시(원문 요지): JD에서 필수/우대 기술스택·도메인 추출 → Title+Skill(2~3개)+Domain만으로
  Boolean 검색식 산출(연차·지역·OTW 제외) → 그 검색식을 Phase 2-LinkedIn `searchKeyword=`에 주입.
- 이번 작업방 범위: **1단계 = "만들어만 놓고 안 쓰는 구멍" 막기.** 3단(정밀/표준/확장)·완화 루프는 다음 작업방.

## ① 현재 상태 (file:line 증거)

- `tools/multi_position_sourcing/llm_keywords.py:122` — LLM이 LinkedIn/공개웹 채널용 `boolean_query`를
  이미 생성하고, `build_llm_keyword_sessions`가 그것을 `KeywordSession.filters['boolean_query']`에 실어 나른다.
- `tools/multi_position_sourcing/portal_queue_executor.py:38` — `keyword = (session.standard_keyword or "").strip()`.
  **여기서 `filters['boolean_query']`를 읽지 않고 버린다.** → 큐 실행 경로가 평문 키워드만 worker로 넘긴다.
- `tools/multi_position_sourcing/portal_worker.py:366-369` — LinkedIn URL을 `searchKeyword={quote(keyword)}`로
  만든다. 즉 worker에 들어온 `keyword`가 그대로 LinkedIn 검색창에 들어간다.
- 결과: `boolean_query`가 생성은 되지만 `keywords_for_item`(executor)에서 누락되어 LinkedIn까지 **도달하지 못함** = 부분 고아.

## ② 근본 원인

`keywords_for_item`(`portal_queue_executor.py:27`)이 boolean 채널에서도 `standard_keyword`만 추출한다.
boolean 채널(linkedin_rps/public_web)은 AND/OR X-ray 쿼리를 받는데, 이 이음새가 그 사실을 모른다.

## ③ 인수 기준 (AC)

### AC1 (주: 배선) — boolean 채널은 boolean_query를 검색어로 흘려보낸다
- **EARS**: `If 큐 아이템의 KeywordSession이 boolean 채널(linkedin_rps/public_web)이고
  filters['boolean_query']가 비어있지 않으면, then keywords_for_item은 그 boolean_query를
  검색어로 산출해야 한다(평문 standard_keyword가 아니라).`
- **검증**: `./verify.sh` → `pytest tests/test_linkedin_boolean_inject.py`
- **counter-AC(가짜 완료)**:
  - boolean_query가 있는데도 standard_keyword를 반환하면 가짜(=현재 버그 그대로).
  - 평문 채널(saramin/jobkorea)에 boolean_query를 주입하면 가짜 — 그쪽은 AND/OR 미지원, native 필터와 충돌.
  - boolean_query가 비어있을 때 standard_keyword로 정상 폴백 안 하면 가짜(0건 검색 유발).

### AC2 (부: 프롬프트 제약) — 연차·지역·OTW 제외, Title+Skill+Domain만
- **EARS**: `Where LLM 키워드 프롬프트가 boolean 채널용으로 만들어지면, 시스템은 boolean_query를
  Title+Skill+Domain만으로 구성하고 연차·지역·OTW는 제외하라고 지시해야 한다.`
- **검증**: `pytest tests/test_linkedin_boolean_inject.py::...prompt...` — 프롬프트 문자열에 제외 규칙 포함 단언.
- **counter-AC**: 프롬프트가 연차/지역 제외를 한 마디도 안 하면 가짜(LLM이 "경력 5년" 등을 boolean에 넣어 native 필터와 충돌).

> counter-AC는 최소 목록이다. 검증자는 여기 국한하지 않는다.

## ④ Harness 게이트 진행 계획
0 시작자격(clean·red-ledger clean) ✅ → 0.5 워크트리 ✅ → 1 스펙(본 문서) → 2 RED 먼저
→ 3 RED→GREEN 최소변경 → 3.5 배선증명 → 4 verify exit 0 → 5 ship/PR → 6 codex 1차 + Claude 2차 적대검증.

## ⑤ codex 적대검증 정조준
- boolean 채널 판정이 하드코딩 누락 없이 정확한가(public_web도 포함?).
- 평문 채널 폴백이 정말 standard_keyword를 지키는가(회귀: 기존 `keywords_for_item` 테스트).
- boolean_query 중복/공백/순서 처리가 0건 검색을 유발하지 않는가.

## ⑥ SOT 체크리스트
- 읽은 SOT: `CLAUDE.md`(루트), memory `ai-search-no-v4-code`(v4 코드 금지 — v5 자체 경로만).
- 이 변경은 동작(SOT 기술된 검색 키워드 흐름)을 바꾸므로 관련 문서 갱신: `skills/search/references/`에
  `boolean-strategy.md` 신설(STEP A~E), 필요 시 SKILL 동작 설명 한 줄.
- v4 코드 비의존 — `tools/multi_position_sourcing/`(v5) 안에서만 수정.

## ⑦ 비범위 (이번에 안 함)
- 3단(정밀/표준/확장) 검색식 생성, 후보 5명 미만 시 완화 루프, 다건 그루핑 순차 서치 → 다음 작업방.
- saramin/jobkorea의 AND/OR 라이브 검증.

## ⑧ 롤백 절차 (FULL)
PR revert 또는 `git revert <merge>`. 단일 모듈(`portal_queue_executor.py`) + 프롬프트 1줄이라 영향 국소.

## ⑨ 영향 반경 (FULL)
깨지면: LinkedIn 검색이 잘못된 검색어로 0건/오검색. 인증·PII·과금 경로 비접촉(검색어 구성만).
데이터 안전: boolean_query 비었을 때 standard_keyword 폴백을 AC1 counter로 강제 → 0건 검색 방지.

## 적대 검증 로그
(게이트 6에서 채움)
