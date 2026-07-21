---
name: clickup-core-lists
description: 사장님이 "클릭업"이라고 말하면(특히 온톨로지 구축·면접후기 수집·후보자/포지션 데이터 톺아보기·전수 스크레이핑 맥락) 반드시 참조해야 하는 클릭업 정본 리스트 8개의 URL·list_id 사전. "클릭업 톺아봐", "클릭업 면접후기", "클릭업 전체 리스트", "클릭업 데이터 수집", "온톨로지에 클릭업 넣어" 트리거. ClickUp MCP 또는 REST API 호출 시 이 8개 list_id를 순회 대상으로 삼는다.
---

# clickup-core-lists — 클릭업 정본 리스트 8개 (온톨로지·면접후기 수집용)

사장님이 "클릭업(에 기록된 내용) 모두 톺아봐 / 수집해 / 온톨로지에 넣어"라고 하면 **아래 8개 리스트가 전체 범위의 정본(SOT)** 이다. 일부만 보고 "클릭업 다 봤다"고 보고하는 것 금지. 2026-07-07 사장님 지정.

Workspace(팀) ID: `9018789656` / Space: Team Space(`90182734130`)

| # | 리스트 이름 | list_id | URL | 성격 |
|---|---|---|---|---|
| 1 | FY26CandidstesStatus | `901814621142` | https://app.clickup.com/9018789656/v/li/901814621142 | FY26 후보자 진행상태(추천~입사·탈락). **면접후기·전형 코멘트의 1순위 소스** |
| 2 | FY26ClientsPosition | `901814621569` | https://app.clickup.com/9018789656/v/li/901814621569 | FY26 고객사 포지션(직군별 상태) |
| 3 | FY25CandidateStatus | `901804973549` | https://app.clickup.com/9018789656/v/li/901804973549 | FY25 후보자 진행상태 |
| 4 | FY25ClientsPosition | `901804973550` | https://app.clickup.com/9018789656/v/li/901804973550 | FY25 고객사 포지션 |
| 5 | '24Valueconnect_Candidate_Status (Imported From Trello) | `901805123889` | https://app.clickup.com/9018789656/v/li/901805123889 | FY24 후보자(트렐로 이관 — 후기가 description에 있는 경우 多) |
| 6 | '23Valueconnect_candidate_status (Imported From Trello) | `901805123765` | https://app.clickup.com/9018789656/v/li/901805123765 | FY23 후보자(트렐로 이관) |
| 7 | '22Valueconnect_candidate_status (Imported From Trello) | `901805929577` | https://app.clickup.com/9018789656/v/li/901805929577 | FY22 후보자(트렐로 이관) |
| 8 | '21Valueconnect_Candidate_Status (Imported From Trello) | `901805929542` | https://app.clickup.com/9018789656/v/li/901805929542 | FY21 후보자(트렐로 이관) |

태스크 수(2026-07-07 API 실측): 284 / 370 / 518 / 186 / 468 / 618 / 1,234 / 825 = **합계 4,503건**. 수집 완료 보고 시 리스트별 `수집수/전체수` 8줄로 누락 없음을 증명한다.

## 수집 규칙 (온톨로지/면접후기 스크레이핑 시)

1. **8개 전부 순회**한다. task 목록은 `include_closed=true` + `subtasks=true` + 페이지네이션 끝까지 (ClickUp REST `GET /list/{list_id}/task?page=N`은 100건 단위 — `last_page`까지 돈다).
2. task마다 다음을 모두 가져와야 "남김없이"다:
   - task 본문(`description` / `text_content`)
   - **댓글 전체**(`GET /task/{id}/comment`) — 면접후기·전형 피드백은 댓글에 있는 경우가 많다
   - 커스텀 필드, status, 담당자, 날짜
3. 원문 훼손 금지: 요약·의역으로 대체하지 말고 원문을 그대로 저장하고, 파생 요약은 별도 필드에 둔다.
4. 외부 쓰기(댓글 작성·상태 변경)는 이 스킬 범위 밖 — 읽기 전용. 쓰기는 사람 승인 필수(CLAUDE.md §0.2).
5. ClickUp MCP가 끊겨 있으면 REST API 폴백(`CLICKUP_API_TOKEN`, 과거 실증 패턴: PR#317~324 위클리 수집기 참조).

## 관련 정본
- 노션 고객사 정보 페이지(같은 온톨로지 소스): https://app.notion.com/p/valueconnect/bf4ac94452f842309a5ae1b9defcd072?v=cb396e86df3d4ee7931fd0f28328f765 — 고객사별 하위 페이지 안에 **중첩 노션 DB**(예: 빅밸류DB, 테크핀레이팅스DB)가 또 있고 그 안의 페이지들(면접후기·Research·수수료조건·Updates)까지 전부 수집 대상.
- 어드민 고객사 화면: https://admin.valuehire.cc/admin/clients
