# 회사 리서치 — 5필수요소 (사장님 명시 2026-07-09)

(구 `position-register` §1.5의 8요소 중 아래 5개는 6개 미만이어도 예외 없이 필수. 나머지 3개는 출처 있으면 추가.)

| # | 요소 | 예 (BISTelligence) |
|---|---|---|
| 1 | **매출**(연도 명시) | ※미확인이면 그대로 표기, 창작 금지 |
| 2 | **창업연도** | 전신 BISTel 2000년 설립 |
| 3 | **창업자/대표** | ※출처 필수, 공개 발언 quote 있으면 포함 |
| 4 | **투자 단계·규모** | 2021년 반도체 사업부 Synopsys 매각(액시트) |
| 5 | **주요 제품/서비스** | Ontology 기반 AI 플랫폼(Agent가 기업데이터 이해·실행) |

추가 요소(출처 있으면): 상장 여부, 임직원 수, 모기업/계열, 최근 뉴스·신사업.

## 조회 순서
1. Supabase `companies.research` JSON 캐시 (`tools/position-batch/lib/build-offer-bodies.mjs`의 `fetchCompanyFacts()` 재사용).
2. miss 시 `company_news` 최근 5건 제목.
3. 그래도 없으면 WebSearch 1회 — 공식 발표/기사 URL을 `sources[]`로 남긴다.
4. 캐시 저장: `~/.cache/saramin-company-research/<slug>.json`에 요소별 키 + `sources[]`(URL). 확인 못한 요소는 `"revenue": "※미확인"`으로 남겨 다음 실행이 그 칸만 재조사.

## 철칙
- **출처 없는 수치는 절대 창작 금지**(SOT-10 §0 철칙 2). 확인 안 된 줄은 본문에서 통째로 생략.
- 5요소 중 하나라도 ※미확인이면 등록 진행은 하되, 완료 보고에 "회사 리서치 5요소: N/5 확인" 명시(SKILL.md §6 보고 형식).
- 회사소개는 사람인 offerComment·잡코리아 EXEC_WORK·LinkedIn ②단·Gmail companyBrief **4채널 모두 동일 내용**을 쓴다(중복 리서치 금지, 1회 생성 재사용).
