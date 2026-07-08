---
name: codeit-talent-archive-search
description: 코드잇 같은 특정 고객사 재직자/이력 보유자를 LinkedIn·사람인·잡코리아에서 MCP claude-in-chrome으로 검색하고, 그 list 화면과 상세 프로필 페이지를 Valuehire 프로필 아카이버 크롬 익스텐션이 자동으로 로컬 SQLite(+Supabase)에 저장하도록 트리거하는 워크플로우. 사용자가 "코드잇 교육행정리드 찾아줘", "회사명 + 직무로 검색해서 아카이브해", "list 화면이랑 상세 페이지 자동 저장", "프로필 아카이버 + MCP" 같은 요청을 할 때 사용. 회사명·직무명·검색 사이트가 바뀌어도 동일 절차로 동작.
---

# 코드잇/고객사 인재 아카이브 검색 워크플로우

이 Skill은 **MCP claude-in-chrome**으로 검색 URL을 띄우고, 사용자의 로컬 **Valuehire 프로필 아카이버 크롬 익스텐션**(`tools/profile-archiver/`)이 list/상세 페이지를 자동 캡처하도록 만드는 절차입니다.

## 사전 조건 체크 (반드시 먼저 실행)

1. **아카이버 서버 확인**: `curl -s http://localhost:7777/api/health`
   - `ok:true` 이면 진행. 아니면 사용자에게 `cd tools/profile-archiver/server && npm start` 안내.
2. **익스텐션 자동 캡처 ON**: 익스텐션의 `chrome.storage.local.autoCaptureEnabled`가 기본 `true`. 팝업 열어 OFF되어 있으면 사용자에게 토글 안내.
3. **AUTO_TARGETS에 list URL 포함되어 있는지** (`tools/profile-archiver/extension/background.js`):
   - LinkedIn 사람 검색 list: `linkedin.com/search/results/people/` → `linkedin_search_people`
   - LinkedIn 개인 프로필 상세: `linkedin.com/in/` → `linkedin`
   - 사람인/잡코리아: 사이트 루트 매칭(검색 list 포함)
   - 누락된 패턴이 있으면 한 줄 추가하고 `chrome://extensions` 에서 **새로고침** 안내 필수.

## 검색 URL 템플릿

회사명을 `{COMPANY}`, 직무를 `{ROLE_KOR}` (쉼표로 OR 여러개) 자리에 넣어 사용.

| 사이트 | URL 패턴 | 비고 |
|---|---|---|
| LinkedIn 사람 검색 | `https://www.linkedin.com/search/results/people/?keywords={ENCODED_QUERY}&origin=GLOBAL_SEARCH_HEADER` | 로그인 필수. 가장 정확. list 자동 캡처되려면 AUTO_TARGETS에 `linkedin_search_people` 등록되어 있어야 함. |
| 사람인 통합 검색 | `https://www.saramin.co.kr/zf_user/search?searchword={ENCODED_QUERY}` | 일반 사용자는 후보자 직접 검색 불가. 채용공고·기업 정보만 노출. |
| 잡코리아 통합 검색 | `https://www.jobkorea.co.kr/Search/?stext={ENCODED_QUERY}` | 사람인과 동일. 공개 정보 한정. |

쿼리 예시(`코드잇` + `교육행정리드`/`교육행정 매니저`): `"코드잇" ("교육행정리드" OR "교육행정 매니저")` → URL 인코딩.

JavaScript URL 인코딩 한 줄:
```js
encodeURIComponent('"코드잇" ("교육행정리드" OR "교육행정 매니저")')
```

## 실행 순서

### Step 1 — MCP 탭 그룹 확보
```
mcp__claude-in-chrome__tabs_context_mcp({ createIfEmpty: true })
```
이미 있는 탭 ID는 재사용하지 말고 **새 탭**을 만든다(`tabs_create_mcp`).

### Step 2 — 사이트별로 새 탭 + navigate
사이트마다 별도 탭 하나씩 만들고 검색 URL로 이동. 익스텐션의 `chrome.tabs.onUpdated`가 URL 매칭 시 **5~12초 후 자동 캡처**(passive capture)를 시작.

### Step 3 — 자동 캡처 대기 & 상세 진입
- list 페이지 캡처는 약 20~60초(스크롤 보강 포함) 소요.
- 상세 프로필(LinkedIn `/in/{slug}`)은 사용자가 직접 클릭하거나, MCP `read_page` → 후보 링크 추출 → `navigate`로 같은 탭 이동.
- 각 detail URL 진입 시 익스텐션이 자동으로 캡처(5분 dedup 윈도우 적용).

### Step 4 — 검증
```bash
curl -s http://localhost:7777/api/health
# archiveCount 증가량 확인

curl -s 'http://localhost:7777/api/list' | grep -E 'linkedin|saramin|jobkorea' | head -20
```
사용자에게 보고할 항목: 추가된 건수, 사이트별 분류, 텍스트 길이, 스크린샷 장수, `http://localhost:7777/api/list` 링크.

## 자주 나오는 문제

| 증상 | 원인 / 조치 |
|---|---|
| list URL 자동 캡처 안 됨 | AUTO_TARGETS에 패턴 누락. background.js 수정 후 `chrome://extensions` → 익스텐션 카드 새로고침. |
| LinkedIn 검색 결과 비어보임 | 비로그인 상태. 사용자에게 로그인 후 같은 URL 다시 진입 안내. |
| `[자동] 실패: 페이지가 이동했습니다` | SPA에서 "더 보기" 버튼이 링크 이동을 일으킴. 익스텐션이 자동 abort → 사용자가 익스텐션 팝업의 "현재 페이지 저장" 수동 클릭. |
| 같은 URL 중복 저장 안 됨 | 5분 dedup. `chrome.storage.local.recentlySaved` 삭제 또는 5분 대기. |
| 사람인/잡코리아에서 사람을 찾을 수 없음 | 일반 사용자 검색은 채용공고·기업만 노출. 후보자 검색을 하려면 사람인 인재풀(유료)·LinkedIn Recruiter가 필요. |

## 보안·PII 주의

- 저장 데이터는 `tools/profile-archiver/server/data/`에 로컬 저장. `.gitignore` 처리됨.
- Supabase가 `configured`이면 `profile_archives` 테이블에 동기화됨. 외부 노출 위험이 있으면 `.env`에서 키 제거.
- LinkedIn 등 일부 사이트 ToS상 자동 수집은 제한적. **사용자가 직접 보고 있는 화면에서 수동 검색을 통해 도착한 결과**만 저장하는 본 워크플로우는 허용 범위 내로 간주하되, 대량 자동 순회는 금지.

## 호출 예시

사용자: "코드잇의 교육행정리드/매니저를 LinkedIn·사람인·잡코리아에서 찾으면서 list랑 상세 페이지 자동 저장해줘"

1. 서버 health 확인.
2. AUTO_TARGETS 확인 (LinkedIn search list 포함되어 있는지).
3. MCP 탭 3개 생성 → 각 검색 URL로 navigate.
4. 60초 대기 후 `/api/list`로 신규 건수·사이트·텍스트 길이 검증.
5. 사용자에게 결과 보고 + 후보자 상세를 더 캡처하려면 list에서 클릭하라고 안내(자동 캡처 트리거됨).
