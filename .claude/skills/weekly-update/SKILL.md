---
name: weekly-update
description: 밸류커넥트 주간 위클리 미팅 자료를 한 번에 모아 기록하는 스킬. 5영역(① 고객사 포지션 Gmail→ClickUp 등록·중복확인 ② 후보자 추천 메일 집계 ③ AI Search 결과를 ClickUp FY26AI_Search + 밸류어드민 두 곳에 이중 SOT 기록 ④ 지난주 Gemini 회의록 요약 ⑤ admin.valuehire.cc/weekly 회의록 마크다운 생성)을 수집·중복확인 후 기록한다. 매주 금요일 오후 정기 실행. 트리거 — "위클리 업데이트", "위클리 미팅 준비", "주간 회의록", "이번주 위클리", "weekly 문서 갱신", "/weekly 업데이트", "금요일 위클리", "weekly-update", "위클리 자료 만들어", "주간 KPI 집계". 근거 goal 문서 — docs/engineering/weekly-meeting-update-automation-goal-2026-06-29.md
---

# Weekly Update — 주간 위클리 미팅 자료 집계·기록

밸류커넥트의 주간 위클리 미팅 직전에, 흩어진 소스(Gmail·ClickUp·Discord·Gemini 회의록)에서
이번 주 활동을 모아 **회의록 마크다운 1개**를 만들고, AI Search 결과는 **두 정본 저장소에 중복 없이 기록**한다.

> 레포 루트: `/Users/kangsangmo/Desktop/valuehire_v4`(이하 `$REPO`). 작업 전 `git -C $REPO fetch origin` 후 **origin/main 기준**으로 본다(로컬이 뒤처져 있을 수 있음 — 과거 사고).

## 0. 실행 전 — 불변 규칙 (어기면 중단)

1. **ClickUp 쓰기 = 무조건 허용**(사장님 명시). 단 **모든 입력은 중복 확인 후**(중복 행 금지). dedup 키는 `references/data-sources.md` 참조.
2. **후보 PII는 ClickUp·어드민 DB에만.** 회의록 마크다운/SOT 문서에 후보 개인정보 평문 금지(이름+포지션 요약까지만).
3. **숫자는 추정 금지.** 소스에서 확인 못 한 값은 `미집계(사유)`로 남긴다.
4. **노션 DB 뷰 정렬 순서 변경 금지**(create/update만, sort·position 파라미터 금지).
5. LLM 요약이 필요하면 `env -u ANTHROPIC_API_KEY claude -p`(Max 0원) 우선.

## 1. 입출력 계약 (먼저 이 모양을 채운다)

산출 = **단일 JSON**(검수용) + 그것을 렌더한 **회의록 마크다운**. JSON 스키마와 채우는 순서는
`references/output-contract.md` 참조. 5영역을 아래 순서로 채운다.

## 2. 5영역 절차

각 영역은 **수집 → 중복 확인 → 기록**. 데이터 소스 ID·도구는 전부 `references/data-sources.md`에 있다.

### 영역 1 — 고객사 포지션
1. **Gmail `[포지션]` 메일**(제목 시작) 수집 — Gmail MCP `search_threads`로 이번 주 스레드, 본문+첨부 파악(`get_thread`). 첨부 이력서/JD 포함.
2. ClickUp `FY26ClientsPosition`(list `901814621569`)에 **중복 확인 후** 없으면 등록. **상세 JD 없어도 제목은 반드시** 채운다.
3. **담당자 = 그 메일을 보낸 사람.** ClickUp `resolve_assignees`로 이메일→멤버 매핑 후 assignee 지정(매핑 실패 시 `미지정(사유)` 기록).
4. **이번 주 신규 인입**은 회의록 상단에 **불릿으로 강조**.
5. **트웰브랩스**: 해당 고객사 ClickUp 전 포지션을 `complete`로 전이.
6. **코드잇·여기어때·스푼랩스·뤼튼테크놀로지스·어글리랩**: 원티드+자사 채용 URL 리스트(`references/data-sources.md`의 스냅샷)와 대조 → 양쪽 어디에도 없는 ClickUp 활성 포지션은 `complete`. (중복 확인 필수.)

### 영역 2 — 후보자 파이프라인
1. **Gmail `[추천]` 메일** 수집 — `search_threads`. **limit를 실제 스레드 수 이상**으로(기본 10 누락 주의).
2. 내용을 **누락 없이 중복 확인 후** 저장(ClickUp 후보자 보드 `901814621142`).
3. **이번 주 추천자 전원 리스팅 + 총 인원수** 기록(중복 인원 합산 금지 — 고유 인원).

### 영역 3 — AI Search 이중 SOT 기록 ★사장님 핵심
AI Search 결과가 ClickUp 댓글·Discord에 **산포**돼 있다. 모아서 **두 정본**에 중복 없이 기록한다.
- 수집: ClickUp 댓글(`clickup_get_task_comments`) + Discord 4채널 + FY26AI_Search 보드.
- 기록 대상 **둘 다**(한쪽만 = 실패): ClickUp `FY26AI_Search`(`901818680208`) + 밸류어드민 `pipeline_candidates`(admin.valuehire.cc/ai-search-list).
- **양쪽 집합 일치 검사**(고객사+포지션+후보 차집합 0).
- 상세 절차·양식(상세형 9컬럼)·dedup은 **`references/ai-search-recording.md`** 참조. (이 표는 `/weekly` 마크다운이 아니라 두 정본에 기록 — 입자 분리.)

### 영역 4 — 지난주 Gemini 회의록 요약
1. Gmail에서 `from:gemini-notes@google.com` + 제목 `회의록` 최신 1건(지난주분) 검색.
2. **불릿포인트로 요약** + 원문 링크 병기. 본문에 없는 내용 환각 금지.
3. **고객사 관련 정보 업데이트는 온톨로지에도 필수 반영** — `node tools/harness/stage-customer-ontology-sources.mjs`(npm `admin-os:customer-ontology-stage`) 경로/수기. SOT `docs/sot/11-customer-ontology-ingestion.md`.

### 영역 5 — /weekly 회의록 마크다운 생성
1. `$REPO/docs/wiki/work-log/<YYYY-MM-DD>-weekly-meeting.md` 생성(파일명 규칙 준수 — 안 지키면 화면 미렌더).
2. 상단 메타(작성자·작성일·주차 FYxxWxx·기준 기간·지난주 구글독스 링크) + **`<!--WEEKLY_KPI {json}-->`** 블록.
3. WEEKLY_KPI json 스키마는 **`references/weekly-kpi-schema.md`** 참조(타입 어김 = 화면 에러). `JSON.parse` 성공해야 함.
4. 영역 1의 신규 인입 불릿 + 영역 4의 지난주 요약을 본문에 넣는다.
5. 확인: `cd $REPO && npx next dev` 후 `/weekly` 접속 캡처(또는 머지 후 admin.valuehire.cc/weekly 확인).

## 3. 자동 실행 (매주 금요일 오후)
정기 실행은 SOT `docs/sot/13-scheduled-agents-registry.md` 원장에 등록한다(launchd/hermes cron). 등록·검증 절차는 그 SOT를 따른다.

## 4. 마무리 체크
- [ ] 5영역 JSON 채움(미집계는 사유 명시) [ ] ClickUp 등록분 중복 0 [ ] AI Search 두 정본 집합 일치 [ ] 회의록 MD `JSON.parse` 통과 [ ] `/weekly` 화면 확인 [ ] 후보 PII 마크다운 평문 0
