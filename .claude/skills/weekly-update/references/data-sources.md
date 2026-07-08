# Weekly Update — 데이터 소스 원장 (SSOT)

> 각 ID·경로는 2026-06-29 사장님 확정 + 코드 정합 확인. 변경 시 goal 문서와 함께 갱신.

## ClickUp (team `9018789656`)
| 보드 | list_id | 용도 |
| --- | --- | --- |
| FY26ClientsPosition | `901814621569` | 고객사 포지션(영역 1 등록 대상) |
| 후보자 보드 | `901814621142` | 추천 후보 저장(영역 2) |
| FY26AI_Search | `901818680208` | AI Search 정본 ① (영역 3) |

- 댓글 읽기: MCP `clickup_get_task_comments`. 예시 task `https://app.clickup.com/t/9018789656/86exp7bw9`.
- 담당자 매핑: MCP `clickup_resolve_assignees` / `clickup_find_member_by_name`.
- 등록/전이: MCP `clickup_create_task` / `clickup_update_task`.

## Gmail (MCP `mcp__claude_ai_Gmail__*`)
| 라벨/검색 | 용도 |
| --- | --- |
| 제목 `[포지션]` | 영역 1 — 공유 JD(첨부 포함). `search_threads` → `get_thread`로 첨부 파악 |
| 제목 `[추천]` | 영역 2 — 추천 후보. limit를 실제 스레드 수 이상으로 |
| `from:gemini-notes@google.com` 제목 `회의록` | 영역 4 — 지난주 회의록 |

## Discord (guild `814353841088757800`)
AI Search 결과가 산포된 채널 4개:
- `1470955309089554554`
- `1509947322652688587`
- `1504171687862862005` (hermes-agent)
- `1374198644559056986`
- **향후 통합 목표**: `1470955309089554554` + `1504171687862862005` 단일화.
- ⚠️ 레포에는 Discord webhook(쓰기)만 있고 **메시지 읽기 코드 없음**. 읽기는 봇 토큰 GET API 또는 hermes-agent 토큰 재사용이 필요 — 미가용이면 ClickUp 댓글을 1차 소스로 쓰고 Discord는 best-effort, 누락분은 `미집계(Discord 읽기 미가용)`로 표기.

## 밸류어드민 (AI Search 정본 ②)
- 화면: `https://admin.valuehire.cc/ai-search-list`
- 백킹: Supabase `pipeline_candidates` (`source LIKE 'ai_search:%'`). 코드 `app/ai-search-list/_data/loader.ts`.

## /weekly 화면
- 화면: `https://admin.valuehire.cc/weekly`
- 소스: `$REPO/docs/wiki/work-log/*.md` + `$REPO/docs/wiki/weekly-growth-meetings/*.md`. 코드 `app/weekly/_lib/weeklyDocuments.ts`.

## 원티드/자사 채용 URL 스냅샷 (영역 1-6)
- `$REPO/docs/product/b2b/wanted-company-career-url-search-2026-05-08-found-only.csv` — 코드잇·여기어때·스푼랩스·뤼튼테크놀로지스·어글리랩 포함(고객사명·공식 ATS·원티드 URL).
- 라이브 재발굴(필요 시): `node scripts/find-wanted-career-urls.mjs`(Exa API).

## dedup(중복) 키 규약 — 모든 기록에 공통
- 포지션: `정규화(고객사) + 정규화(포지션명)`
- 후보/AI Search: `정규화(고객사) + 정규화(포지션) + 후보식별자(이름 또는 candidate task id)`
- Gmail 출처: `gmail_thread_id` 병행.
- 같은 키 존재 시 **insert 금지 · 필요 필드만 update**.

## 쓰기 게이트
- `tools/gmail-sync`의 `OWNER_SIGNOFF_SOURCE_COLLECTION` 게이트는 `approved`로 통과(사장님 "쓰기 무조건 허용"). dry-run은 게이트 무관.
