# boolean-strategy — JD → Boolean 검색식 설계 규칙 (STEP A~E)

> AI Search 가 LinkedIn(RPS)·공개웹 X-ray 검색에 넣을 **Boolean 검색식**을 JD에서 산출하는 규칙.
> 코드 출처: 생성 = `tools/multi_position_sourcing/llm_keywords.py`(`_build_prompt` → `boolean_query`),
> 주입 = `tools/multi_position_sourcing/portal_queue_executor.py`(`keywords_for_item` → LinkedIn `searchKeyword=`).
> boolean 채널 집합 단일 출처: `tools/multi_position_sourcing/models.py:BOOLEAN_CHANNELS`.

## 핵심 불변식

- **Boolean 검색식 = Title(직무) + Skill(변별력 2~3개) + Domain(도메인/산업) 만.**
- **연차·경력년수·지역·근무지·OTW(연봉/처우)는 절대 검색식에 넣지 않는다.**
  이 조건들은 검색의 native 필터/2패스(Phase 2)가 따로 처리한다. Boolean 에 넣으면 충돌해 0건이 난다.
- boolean 채널(linkedin_rps/public_web)만 Boolean 을 받는다. 사람인/잡코리아는 평문 키워드(AND/OR 라이브 미검증).

## STEP A — JD 파싱
JD 원문에서 추출한다:
- **필수 기술스택**(must-haves): 그 직무에 반드시 필요한 기술.
- **우대 기술스택**(nice-to-haves): 있으면 가점.
- **도메인/산업**: 회사가 속한 시장(fintech, commerce, adtech, 서브컬쳐 등).
- 연차·지역·연봉은 추출하되 **Boolean 에는 쓰지 않는다**(native 필터로 넘긴다).

## STEP B — 구성요소 선별
- **Title**: 직무명을 국문/영문·표기변형으로 (예: "Backend Engineer" / "백엔드 개발자" / "서버 개발자").
- **Skill**: 필수 기술 중 **변별력 높은 2~3개만** (너무 흔한 건 제외 — "Git" 같은 건 변별력 0).
- **Domain**: 도메인 1~2개 (국/영 표기).

## STEP C — 3단 검색식 (정밀 → 표준 → 확장)
| 단계 | 구성 | 목적 |
|---|---|---|
| **정밀** | Title AND (Skill 2~3 모두 AND) AND Domain | 가장 적합한 소수 후보 |
| **표준** | Title AND (Skill 2~3 OR 묶음) AND Domain | 적정 풀 |
| **확장** | Title AND (Skill OR) — Domain 완화/제거 | 풀 넓히기 |

형식: `("A" OR "B") AND ("C" OR "D") AND ("E")` 한 줄. 따옴표로 구절을 묶는다.

## STEP D — 주입
- 산출된 **정밀** 검색식을 Phase 2-LinkedIn `searchKeyword=` 에 먼저 주입한다.
- 현재 배선: `KeywordSession.filters['boolean_query']` → `keywords_for_item` 이 boolean 채널이면
  이 값을 검색어로 채택 → `portal_worker._goto_search_surface` 가 `searchKeyword={quote(...)}` 로 LinkedIn URL 생성.
- boolean_query 가 비면 `standard_keyword` 로 폴백(0건 검색 방지).

## STEP E — 완화 (다음 단계 — 아직 미구현)
- Phase 2-1 통과 후보가 **5명 미만**이면 정밀 → 표준 → 확장 순으로 검색식을 완화해 재검색한다.
- 다건 발견 시: 기술 유사도 / 연차대 / 도메인으로 그루핑 → 그룹별 순차 서치.

> 2026-06-24 1단계 구현 범위: STEP D 의 주입 구멍(boolean_query 가 LinkedIn 까지 도달) + STEP B 의
> "연차·지역·OTW 제외" 프롬프트 강제. STEP C(3단)·STEP E(완화 루프)는 후속 작업방.
