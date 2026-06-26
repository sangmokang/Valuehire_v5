---
name: humansearch
description: 사장님이 채용 사이트(LinkedIn Recruiter/RPS·사람인·잡코리아)에 검색을 직접 걸어둔 리스팅 화면을 받아, 후보 프로필을 하나씩 열어 스크린샷 저장 → JD와 점수(학력30·직무50·논리10·이직안정10) 매김 → 합격(70점+) 후보만 묶어 Discord #ai_search 로 보내는 스킬. 검색어 생성·필터 입력은 하지 않는다(사람이 이미 걸어둠). 트리거 — "humansearch", "휴먼서치", "이 화면 순회해서 후보 솎아줘", "리스팅 돌면서 채점해서 디스코드로", "지금 보이는 검색결과로 후보 찾아 #ai_search 로", 포지션명/positionId 를 주며 "이 검색결과 순회". search/multisearch(스킬이 검색까지 함)와 달리 humansearch 는 사람이 걸어둔 결과를 순회·채점·발송만 한다.
---

# humansearch — 사람이 걸어둔 검색을 순회·채점·발송

## ⛔ 공통 SOT 시작 게이트 (절대 생략 금지)

이 스킬이 발동되면 **작업·코딩·브라우저 조작·외부 쓰기 전에 먼저 기존 정의를 회수한다.**
이 게이트를 건너뛰면 SOT 위반이다.

반드시 먼저 읽고 보고:
- 루트 SOT: `CLAUDE.md`
- 작업 루프: `docs/harness.md`
- 관련 SOT: `docs/sot/`
- 이 스킬 설정: `skills/humansearch/humansearch.config.json`
- 기존 구현 진입점: `tools/multi_position_sourcing/humansearch.py` 및 이미 존재하는 순회/발송 경로
- 과거 메모리·로그·기존 구현 검색 결과

먼저 보고할 5가지:
- 읽은 경로
- 기존 구현 진입점
- 재사용·확장할 파일/함수
- 새 파일 필요 여부와 이유
- 외부 쓰기 여부와 승인 게이트

강제 금지:
- 기존 정의·구현 회수 전 새 코드 작성 금지
- 기존 경로로 가능한데 새 파일·새 러너·새 등록 스크립트 작성 금지
- 스펙을 사후에 추가해 현재 행동을 정당화 금지
- 정의 미발견·스펙 충돌·죽은 참조 발견 시 추측 진행 금지 → **STOP** 후 보고
- 테스트 약화·삭제 금지

외부 쓰기는 항상 L3:
- Discord, ClickUp, 이메일, 채용사이트, 사람인·잡코리아·LinkedIn/RPS 게시·등록·댓글·필드 업데이트·발송은
  사장님 **명시 승인** 전까지 dry-run, 초안, 저장까지만 한다.
- 알람 폭탄 금지. 여러 후보·여러 항목은 한 메시지 또는 한 댓글로 묶는다.
- `profile_url` 등 필수 URL/필드는 쓰기 직전 무결성 검사를 통과해야 한다.

사장님이 검색을 **이미 걸어둔** 상태에서 시작한다. 검색어 생성·필터 입력은 이 스킬의 일이 아니다
(그건 `search`/`multisearch`). humansearch 는 **목록 순회 → 프로필 1건씩 열기 → 채점 → 합격자
묶어 Discord 발송**만 한다.

설정 단일 출처: `skills/humansearch/humansearch.config.json` (가중치·합격선·제외·순회 규칙).
판정 로직 단일 출처: `tools/multi_position_sourcing/humansearch.py`.

## ⛔ 안전 불변식 (항상)
- **제안·메일 "보내기"는 절대 자동으로 누르지 않는다(SOT 3).** humansearch 는 후보 "브리핑"만 보낸다.
- **사장님이 크롬을 쓰는 동안에는 즉시 양보**하고, 손을 떼면 자동으로 다시 이어 한다(SOT 2 / R4).
  봇처럼 창 여닫기·URL 연타·알람 후 무한 재시도 하지 않는다.
- **보안 챌린지(캡차·봇차단·로그인 리다이렉트) 감지 시 즉시 STOP.** retry 금지(계정 잠금).
- 행동 전 **DOM 덤프**로 셀렉터를 확인한다(SOT23 evidence-first). 추측 셀렉터 금지.

## 입력
다음 중 하나가 있으면 시작: 포지션명 · ClickUp positionId · 현재 보이는 검색결과 URL.
- positionId 가 있으면 ClickUp JD 를 읽어 `Position`(must_haves/nice_to_haves) 으로 만든다(기존 경로 재사용).
- 화면만 있으면 보이는 포지션 컨텍스트 + 사장님 1줄 요약을 JD 로 쓴다.
- 채널은 활성 탭 URL(talent pool 패턴)로 추론하거나 사장님이 지정. 안전하면 3채널 **병렬**.

## 순회 (config.traversal)
- 최대 **10페이지**, 페이지는 **랜덤 순서**로 오간다(`start=0,25,50…` 무작위 — 순차 패턴 회피).
- **너무 빠른 속도 금지 — 사람처럼 천천히.** 링크드인은 프로필/키워드 간 20~60초 랜덤,
  사람인·잡코리아는 카드 간 3~8초. 링크드인은 **Open to work** 위주, 랜덤값 부여 후 하나씩 클릭.
- 채널별 "결과수 판단 트리"(0~4 포기 / GOLD 전수 / 81~300 상위 일부)는 SOT22 를 그대로 따른다.

## 프로필 1건 처리
1. 상세 진입(라이선스 차감 0) → **화면 스크린샷 1장 저장**(`~/.vh-search-results/{channel}/{date}/...`).
2. 레쥬메 텍스트 추출 → `CapturedProfile`(education·skills·employment_history·summary·evidence_paths) 구성.
3. **채점 전 하드 제외**(`hard_exclude_reason`): 프리랜서·잦은 단기이직(12개월 미만 2회+)·전문대 등.
   - 사람인·잡코리아만 학교 컷. **지방 국공립대·단국대 이상은 허용.** 링크드인은 학교 컷 미적용.
   - "하위권 지방 사립"의 미세 판단은 기계가 다 못 한다 → 의심되면 사람/LLM 판단으로 거른다.
4. 통과한 후보만 채점(`score_humansearch`): 학력30·직무50·논리10·이직안정10 → 0~100.

## 발송 (config.output)
- **70점 이상**만 Discord **#ai_search** 로. 합격자 여러 명을 **한꺼번에** 보낸다.
- 메시지 포맷은 기존 `discord_briefing.format_discord_candidate_briefing()` 재사용
  (Profile URL · 점수 · 학력/경력 요약 · JD 와 잘 맞는 부분 · 안 맞는 부분 · 근거).
- ⚠️ **발송 직전 반드시 `eligible_matches_for_send(matches)` 로 거른다** — 이 함수가
  점수 70+ **그리고** `is_valid_profile_url()` 통과 후보만 남긴다(단일 관문). 빈값·내부공백·
  상대경로·`javascript:void`·비http URL 은 여기서 차단(사장님 0순위: 프로필 url 절대 오류 없어야 함).

## 비범위
검색어 생성·필터 자동 입력(=search/multisearch), 제안/InMail/메일 발송(=사람 수동 게이트),
새 DOM 셀렉터 표 작성(=SOT23 재사용).
