# SOT 22 — 인재검색 필터·DOM 세팅 SSOT (사람인·잡코리아·링크드인)

> **이 문서가 AI Search 3채널 검색의 단일 기준(SSOT)입니다.**
> 검색(후보 발굴)을 돌리기 전에 **반드시 먼저 읽습니다.** 채널을 섞지 않습니다.
> 기계가 읽는 전체 명세(셀렉터·입력법·완화 폴백·제안 모달까지)는 같은 폴더의
> **[`22-talent-search-filters.json`](./22-talent-search-filters.json)** 입니다. 이 `.md`는 사람용 요약 + 그 JSON으로 가는 입구입니다.
>
> 버전: v2.0.0 · 최종 정리 2026-06-25

---

## ⛔ 채널 혼동 방지 — 한눈에 (제일 중요)

3채널은 **URL·입력 방식·결과수 임계가 전부 다릅니다.** 절대 섞지 않습니다.

| 구분 | 사람인 | 잡코리아 | 링크드인 RPS |
|---|---|---|---|
| **인재풀 URL** | `https://www.saramin.co.kr/zf_user/memcom/talent-pool/main/search` | `https://www.jobkorea.co.kr/corp/person/find` | `https://www.linkedin.com/talent/search` |
| **키워드 입력** | OR/AND/NOT 3박스, `keyboard.type`+Enter (fill 금지) | `#txtKeyword`에 **클립보드 붙여넣기**(객체 mutate만으론 미반영) | 자연어 검색이 1급, 클립보드 붙여넣기 |
| **필터 적용** | 좌측 필터 + 빠른필터 칩 | `window.searchcondition` 객체 + DOM 입력칸 이원화 | 자연어/파라미터(좌측 폼은 보조) |
| **결과수 읽기** | `span.list_count` "총 N 명" | "전체 N개" 정규식 | 상단 "X results" |
| **GOLD 전수 임계** | 5~80명 | 5~80명 | **5~60명**(더 낮음) |
| **봇 가드** | 캡차 감지 시 STOP | `/captcha|보안문자/` STOP | 키워드 간 **20~60초** 랜덤 필수 |

> 자세한 셀렉터·결과수 판단 트리(0~4 / 81~300 / 300+ 등)는 JSON의 각
> `channels.<채널>.dom_selectors` 와 `result_count_decision_tree`를 본다.
>
> 위 표는 **DOM 혼동이 일어나는 포털 3채널**만 다룬다. JSON에는 `chatgpt_claude_ai`
> (ChatGPT/Claude.ai 대화형 AI 검색 채널)도 들어 있다 — 포털이 아니라 셀렉터·결과수 트리가
> 없는 게 정상이며, 사장님 원본 채널이므로 지우지 않는다.

---

## 절대 규칙 (global_rules — 전 채널 공통)

- **R0** 인재 검색 ≠ 채용공고 검색. `search?searchword=` 같은 일반 검색 URL 금지 → talent pool URL만.
- **R1** 필터는 하나씩 차분히(키워드→직무→경력→지역→학력), 단계 사이 1~2초.
- **R2** 캡차·봇차단·로그인 리다이렉트 감지 → **즉시 STOP, retry 금지**(계정 잠금).
- **R3** 사장님이 직접 chrome 만지는 중엔 자동화 액션 0(세션 충돌 방지). ← SOT R4(양보·자동 재개)
- **R4** 인재DB 라이선스 필요. 차감 버튼(검색/제안 발송)은 사람 컨펌 후. 상세 진입·저장은 차감 0.
- **R5** ⛔ **채널을 직무로 가르지 않는다.** "잡코리아=IT, 사람인=마케팅" 식 매핑 금지 — 모든 직무를 전 채널 전방위.
- **R6** 검토 가치 있는 카드는 점수와 무관하게 즉시 저장(차감 0).
- **R_evidence_first** 행동 전 DOM 덤프 필수. 셀렉터 추측이 fresh DOM 덤프를 못 이긴다 — 페이지 바뀌면 재확인 후 행동.

> 발송(제안·메일·InMail) **"보내기"는 절대 자동으로 누르지 않는다 — 항상 사람이 마지막에 누른다**(SOT 불변식 3 / R12).

---

## 키워드 전략 (요약)

JD를 5축으로 분해 → 축마다 OR/AND/NOT 배정.
- **산업**(AND, 1개만) · **직무**(OR, 동의어 묶음) · **스킬·툴**(OR, 1~2개) · **경력**(좌측 필터, ±1~2년) · **제외**(NOT)
- 핵심: **AND 1개로 보통 90% 좁아진다.** specific AND 여러 개 = 결과 0명.

전체 파생어 규칙·우선순위는 JSON `keyword_strategy` 참조.

---

## 이 SSOT의 출처 (source_of_truth)

- 현재 실행 스킬: `~/.codex/skills/ai-search/SKILL.md`, `skills/search/SKILL.md`, `skills/multisearch/SKILL.md`
- ★ 역사적 원본: `~/.claude/skills/talent-search/SKILL.md` (사장님 화면 캡처 확인, 2026-05-21)
- DOM 셀렉터 원칙: `docs/sot/23-channel-dom-selectors.md` (evidence-first)
- 채널별 역사적 스킬: `~/.claude/skills/saramin-talent-sourcing/SKILL.md` / `~/.claude/skills/jobkorea-talent-sourcing/SKILL.md` / `~/.claude/skills/linkedin-rps-jd-set-builder/SKILL.md`
- 현재 실행 엔진: `tools/multi_position_sourcing/` (`dry_run`, `queue_runner`, `channel_search_render`, `portal_queue_executor`, `portal_autologin`)
- 옛 코드 경로: `22-talent-search-filters.json`의 `code_files_MISSING`에만 보존(현재 실행 경로로 쓰지 않음)
- 라이브 검증일: 2026-05-22(사람인) · 06-16/06-22(잡코리아) · 06-22(링크드인) · 06-23(SOT23)

---

## 알려진 한계 (known_limitations)

- 사람인 학력 체크박스·연봉 범위의 정확한 CSS id: 항목은 명시됨, 개별 id는 라이브 DOM 덤프로 확정.
- 잡코리아 education/jobtype 등 구체 코드값: 항목은 명시됨, 코드값은 `searchcondition` 라이브 덤프로 추출.
- 링크드인 RPS 좌측 필터 패널 정밀 셀렉터: 자연어 검색이 1급이라 폼 셀렉터 미구현 → 라이브 덤프로 확정.
- 3채널 동시 한 바퀴 라이브 실증은 미완(채널별 개별 라이브 검증은 됨).
