# WEEKLY_KPI 블록 스키마

`/weekly` 화면(`app/weekly/_lib/weeklyDocuments.ts`의 `WeeklyKpi` 타입)이 파싱하는 주석 블록.
회의록 마크다운 상단 메타 직후에 둔다. **코드펜스 밖**의 `<!--WEEKLY_KPI ... -->` 주석만 파싱된다. `JSON.parse` 성공 필수.

## 형태 (타입 그대로 — 어기면 화면 에러)
```
<!--WEEKLY_KPI
{
  "week": "FY26W27",
  "period": "2026-06-22 ~ 2026-06-28 (KST)",
  "goal": { "label": "1일 1추천", "weekly": 5, "monthly": 20, "successRate": 0.05 },
  "cards": [
    { "key": "newClients",      "label": "이번 주 신규 의뢰 고객사", "value": 0, "unit": "곳", "prev": null, "avg4w": null, "source": "근거(ClickUp 직조회 …)" },
    { "key": "activePositions", "label": "전체 활성 포지션",        "value": 0, "unit": "건", "prev": null, "avg4w": null, "source": "근거" },
    { "key": "staleReview",     "label": "검토 필요(30일+)",        "value": 0, "unit": "건", "prev": null, "avg4w": null, "source": "근거" },
    { "key": "recommended",     "label": "이번 주 추천 인원",        "value": 0, "unit": "명", "prev": null, "avg4w": null, "source": "근거" }
  ],
  "goalProgress": { "recommended": 0, "target": 5, "pct": 0 },
  "aiSearch": {
    "summaryLine": "한 줄 요약",
    "intake": { "newThisWeek": 0, "totalActive": 0 },
    "recommended": [
      { "name": "", "client": "", "position": "", "stage": "", "score": "확인필요" }
    ],
    "unacted": [
      { "client": "", "position": "", "ageDays": "확인필요" }
    ]
  }
}
-->
```

## 규칙
- `value`/`prev`/`avg4w`는 숫자 또는 `null`. 확인 못 한 값은 `null` + `source`에 사유.
- `aiSearch.recommended[]` 필드는 `name/client/position/stage/score`만 — **상세형 9컬럼은 여기 넣지 않는다**(타입 불일치). 9컬럼은 `ai-search-recording.md`대로 ClickUp·어드민 두 정본에 기록.
- `score`가 없으면 문자열 `"확인필요"`(0이나 추정 금지).
- 작성 후 검증: `node -e "JSON.parse(require('fs').readFileSync('<파일>','utf8').match(/<!--WEEKLY_KPI([\\s\\S]*?)-->/)[1])"` 가 에러 없이 끝나야 함.

## 실제 예시
`$REPO/docs/wiki/work-log/2026-06-15-weekly-meeting.md`(FY26W25) 참고 — cards 4개 + aiSearch.recommended/unacted 채운 골든 샘플.
