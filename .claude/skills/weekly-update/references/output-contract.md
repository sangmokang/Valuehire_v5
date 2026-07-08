# Weekly Update — 입출력 계약 (SDD)

스킬 산출 = 아래 **단일 JSON**(검수용) → 영역 5에서 회의록 마크다운으로 렌더.
5영역을 순서대로 채운다. 확인 못 한 값은 `미집계(사유)` / `null`.

```json
{
  "week": "FY26W27",
  "period": "2026-06-22 ~ 2026-06-28 (KST)",
  "positions": {
    "newFromGmail": [
      { "subject": "[포지션] …", "sender": "name@co", "attachments": ["resume.pdf"],
        "dedupKey": "정규화(회사)+정규화(포지션)", "alreadyInClickUp": false,
        "clickupTaskId": null, "assignee": "name@co", "titleOnly": false }
    ],
    "newIntakeBullets": ["- 이번 주 신규 인입 …"],
    "twelvelabsCompleted": ["86exxxx"],
    "wantedSync": [
      { "client": "코드잇", "liveUrls": ["…"], "clickupActive": ["…"], "toComplete": ["…"] }
    ]
  },
  "candidates": {
    "recommendedThisWeek": [ { "name": "", "client": "", "position": "", "dedupKey": "회사+포지션+후보" } ],
    "count": 0
  },
  "aiSearch": {
    "rows": [ { "client":"", "position":"", "orderDate":"", "dupCleared":true,
                "aiSearch":"", "humanSearch":"", "batch1":"", "batch2":"", "batch3":"", "pipeline":"" } ],
    "writtenTo": { "clickupFY26AISearch": 0, "pipelineCandidates": 0, "setEqual": true }
  },
  "lastWeekRecap": {
    "source": "gmail:gemini-notes",
    "bullets": ["…"],
    "ontologyUpdates": [ { "client": "", "fact": "" } ]
  },
  "weeklyMarkdownPath": "docs/wiki/work-log/2026-06-27-weekly-meeting.md"
}
```

## 모드
- **dry-run**(기본): 수집·검수만, 외부 쓰기 0. JSON만 출력해 사장님 검수.
- **write**: ClickUp 등록/전이 + `pipeline_candidates` upsert + 회의록 마크다운 생성·커밋.

## 완료 판정 (이 칸들이 채워지고 검사를 통과해야 "기록 완료")
- `positions.newFromGmail[].titleOnly=false 또는 title 존재` (제목 빈 등록 금지)
- `aiSearch.writtenTo.setEqual=true` (두 정본 일치)
- `candidates.count == recommendedThisWeek 고유 인원`
- `weeklyMarkdownPath`의 WEEKLY_KPI가 `JSON.parse` 통과
