# AI Search 이중 SOT 기록 (영역 3 상세)

목표: 산포된 AI Search 결과를 **두 정본**에 중복 없이 일원화. 한쪽만 기록 = 실패.

## 정본 2곳
1. **ClickUp `FY26AI_Search`** list `901818680208` — 포지션/배치 단위(상세형 9컬럼).
2. **밸류어드민 `pipeline_candidates`**(`admin.valuehire.cc/ai-search-list`) — 후보자 단위.

> 입자가 다르다(ClickUp=포지션, 어드민=후보자). 동일 AI Search 이벤트를 두 입자로 기록하되, 집합 일치 검사는 `고객사+포지션+후보` 키로 한다.

## 수집 순서
1. ClickUp 댓글 — 대상 task들에서 `clickup_get_task_comments`로 AI Search 결과 댓글 파싱.
2. Discord 4채널(`data-sources.md`) — 읽기 가용 시 이번 주 메시지에서 (고객사·포지션·후보·점수) 추출. 미가용이면 `미집계(Discord 읽기 미가용)`.
3. FY26AI_Search 보드 기존 행 — 이미 기록된 것 확인(중복 방지).

## 상세형 9컬럼 (ClickUp FY26AI_Search custom field/본문)
`고객사 | 포지션 | Order 날짜 | 중복/보드 정리 | AI Search | Human Search | 추천 1 Batch 실행 | 추천 2 Batch 실행 | 추천 3 Batch 실행 | 현재 추천 파이프라인`
- Batch 실행 칸엔 ClickUp task id(예: `86exxn9yx`) 병기.
- 값 없으면 `미집계(사유)`.

## 기록 + 중복 확인 절차
1. dedup 키 = `정규화(고객사)+정규화(포지션)+후보식별자`.
2. **ClickUp 측**: `clickup_filter_tasks`(list `901818680208`)로 키 재조회 → 있으면 `clickup_update_task`, 없으면 `clickup_create_task`(중복 행 금지).
3. **어드민 측**: `pipeline_candidates`에 `source='ai_search:<채널>'`로 upsert(같은 후보 키 중복 금지).
4. **양쪽 집합 일치 검사**: 두 저장소의 `(고객사+포지션+후보)` 집합 차집합 = 0. 불일치 시 어느 쪽 누락인지 로그(`writtenTo.setEqual=false`).

## 출력(영역 3 JSON 조각)
```json
"aiSearch": {
  "rows": [ { "client":"", "position":"", "orderDate":"", "dupCleared":true,
              "aiSearch":"", "humanSearch":"", "batch1":"86exx", "batch2":"", "batch3":"", "pipeline":"" } ],
  "writtenTo": { "clickupFY26AISearch": 0, "pipelineCandidates": 0, "setEqual": true }
}
```
