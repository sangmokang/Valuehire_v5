# SOT 25 — AI Search 실행 프로세스 표준 (spec-driven)

> 이 문서는 사람용 입구입니다. **기계가 읽는 전체 명세는 같은 폴더의
> [`25-ai-search-execution-process.json`](./25-ai-search-execution-process.json)** 입니다.
>
> 사장님 지시(2026-06-25): "니가 체크해서 니가 실행해. 이 과정 프로세스로
> 스펙 드리븐으로 JSON으로 표준화해서 붙여." → AI Search 한 턴을 단계·게이트로 박았습니다.
>
> 버전: v1.1.0 · 2026-07-07

---

## 한 줄 요약

positionId/URL 하나 받으면 → **내가 점유·캡차를 직접 체크하고** → 사장님이 크롬 쓰면
잠깐 양보했다 손 떼면 자동 재개 → JD 읽고 → 키워드 5축으로 쪼개 → 3채널 전방위로 찾고 →
점수 매기고 → 표준 JSON으로 #ai_search와 FY26AI_Search 칸반에 정리. **보내기는 절대 자동으로 안 누름.**

## 10단계 (JSON `stages`와 1:1)

| # | 단계 | 핵심 |
|---|---|---|
| 0 | 사전 점검 | v5에서만. 브라우저 경로(익스텐션/CDP :9222) 확인 |
| 1 | 점유·캡차 게이트 | 탭 조회 → 채널별 {READY/OCCUPIED/BLOCKED} 자동 판정 |
| 2 | 양보·자동 재개 | 점유 중엔 액션 0, 손 떼면 자동 재개(방치 금지) |
| 3 | JD 확보 | SOT24에 있으면 그걸로, 없으면 채용홈에서 직접 추출 |
| 4 | 키워드 5축 | 산업·직무·스킬·경력·제외. AND 1개로 90% 좁힘 |
| 5 | 채널 검색·저장 | talent pool URL만, 전방위, 상세 진입=저장(차감 0) |
| 6 | 적합도 평가 | 4축 점수, 85+ 강력추천 / 70~84 후보 / 70↓ 제외 |
| 7 | 표준 출력 | 필수 4필드(profile_url·score·why_fit·profile_summary) + FY26AI_Search 등록 계약 |
| 8 | JD 템플릿 레인 | 신규/오픈 포지션이면 LinkedIn/RPS JD 템플릿까지 |
| 9 | 결과 보고 | 채널별 인원·템플릿 상태·다음 키워드·산출물 경로 |

## 절대 게이트 (INV — 약화 금지)

- **INV2** 사장님 크롬 점유 → 양보, 손 떼면 **자동 재개**.
- **INV3** 발송(제안·메일·InMail) **보내기 자동 금지** — 사람이 마지막에 누름.
- **INV4** 캡차·봇차단 감지 → 그 채널 **즉시 STOP, 자동 우회 금지**.
- **INV5** 채널을 직무로 가르지 않는다 — 전 직무 전 채널 전방위.
- **INV6** 상세 진입·저장은 차감 0 → 발견 즉시 저장. 차감 버튼만 사람 컨펌.
- **INV14** ClickUp 기록은 **FY26AI_Search list `901818680208`**
  (`https://app.clickup.com/9018789656/v/li/901818680208`) 고정. AI Search와 Humansearch 모두
  부모 Task + 후보 Subtask 구조로 남긴다. 생성 전 부모 Task와 후보 `profile_url` 중복검사를
  반드시 수행하고, 프로필 저장 증거 없는 후보는 등록하지 않는다.

## ClickUp 등록 계약

- 대상: FY26AI_Search 보드/list `901818680208`.
- 구조: 포지션 부모 Task 1개 + 합격 후보(70+) Subtask.
- 중복검사: 부모 Task 검색 후 재사용, 후보는 같은 부모 아래 `profile_url` 로 Subtask 검색 후 생성.
- 저장 증거: `screenshot`/`evidence_paths`/archive id 등 프로필 저장 증거가 있어야 등록 가능.
- fail-closed: list id 불일치, 중복검사 누락, `profile_url` 무효, 저장 증거 누락, 출력 필수 4필드 누락이면 생성 금지.
- 쓰기 게이트: ClickUp create/update/comment 는 L3 외부 쓰기라 사장님 현재 턴 명시 승인 전까지 dry-run/계획만.

## 연결된 SOT

- 채널 필터 입력법: `22-talent-search-filters.json`
- JD 평가기준: `24-position-jd-sot.json`
- 후보 출력 계약: `25-ai-search-execution-process.json`의 `output_contract.required_fields`
  (`profile_url`, `score`, `why_fit`, `profile_summary`) + `tools/multi_position_sourcing/models.py`의 `PositionMatch`
- ClickUp 등록 계약: `25-ai-search-execution-process.json`의 `clickup_registration_contract` +
  `tools/multi_position_sourcing/humansearch_register.py`의 FY26AI_Search 등록 경계
