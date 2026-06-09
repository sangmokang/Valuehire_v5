---
name: position-registration
description: Valuehire 포지션 등록 Skill. Wanted/ClickUp URL 또는 JD 본문을 받아 ClickUp FY26ClientsPosition/칸반에 중복 없이 등록하거나 기존 태스크에 근거 댓글로 연결한다. Discord DM에서 '포지션 등록', '채용공고 등록', '원티드 등록' 요청을 처리할 때 사용한다.
---

# Valuehire 포지션 등록

## 언제 쓰나

사용자가 다음처럼 말하면 이 Skill을 사용한다.

- "포지션 등록해줘"
- "채용공고 등록"
- "원티드 등록 https://www.wanted.co.kr/wd/..."
- Wanted 채용공고 URL, ClickUp URL, JD 본문을 주며 ClickUp/칸반에 넣어 달라고 요청

후보자 "검색", "서치", "AI Search", "롱리스트" 요청과는 다르다. 등록 요청은 포지션 인입 업무이고, 후보자 소싱 업무가 아니다.

## 안전 원칙

1. 중복 생성 금지
   - 같은 회사/포지션 또는 같은 Wanted URL이 이미 ClickUp에 있으면 새 태스크를 만들지 않는다.
   - 기존 태스크에 원본 URL/JD 근거 댓글을 연결하고 태스크 URL과 댓글 ID를 보고한다.

2. 외부 게시 금지
   - 사람인, 잡코리아, LinkedIn/RPS, Gmail 발송은 이 Skill의 기본 범위가 아니다.
   - 외부 게시/발송은 별도 SOT 게이트와 사장님 명시 승인이 있을 때만 진행한다.

3. 비밀값 보호
   - ClickUp/Supabase/API 토큰 값은 절대 출력하지 않는다.
   - 로그나 보고에는 키 이름과 성공/실패만 남기고 값은 `[REDACTED]`로 취급한다.

4. fail-closed
   - Discord 라우팅은 허가된 개인 DM에서만 등록 경로로 보낸다.
   - 입력이 부족하면 등록하지 말고 Wanted URL, ClickUp URL, 또는 JD 본문을 요청한다.

## 입력 판정

지원 입력:

- Wanted URL: `https://www.wanted.co.kr/wd/...`
- ClickUp URL: `https://app.clickup.com/t/...`
- JD 본문: 회사소개/주요업무/자격요건/우대사항 등을 포함한 긴 텍스트
- 짧은 회사·직무명: 명시적으로 "포지션 등록" 의도가 있을 때만 허용

라우팅 우선순위:

1. "등록/추가/생성/올려/넣어"와 "포지션/채용공고/JD/원티드/Wanted"가 함께 있으면 등록 요청으로 본다.
2. 등록 요청은 후보자 AI Search보다 우선한다.
3. "서치/Search/검색/롱리스트"만 있으면 후보자 검색 Skill로 보낸다.

## 실행 절차

전체 흐름은 `tools/multi_position_sourcing/position_registration.py`의 `run_position_registration()`이 조율한다. 기본은 `dry_run=True`(계획만 산출, ClickUp 쓰기 없음)이며, 실제 반영은 `dry_run=False`로 호출할 때만 일어난다.

1. 입력 추출 — `posting_extractor.extract_posting()`
   - URL이 있으면 httpx 우선 fetch, 차단/빈 HTML/JD 신호 부족이면 Playwright 렌더 폴백을 시도한다(주입형 `http_fetch`/`render_fetch`, 테스트는 fake 주입).
   - HTML은 표준 라이브러리로만 파싱한다(`og:site_name`/`og:title`/JSON-LD JobPosting + 주요업무/담당업무/자격요건/우대사항/회사소개 헤딩).
   - `<img>`/`og:image` 이미지를 urljoin·dedup으로 수집하고, 주입형 `image_downloader`로 받아 `artifacts/position_registration` 아래에 근거 이미지로 저장한다(data: URI는 건너뜀).
   - JD 본문 붙여넣기(`pasted_jd`)면 fetch 없이 `parse_result.text`로 바로 `ExtractedPosting(ok=True)`를 만든다.
   - 차단/빈 결과이고 회사/직무도 못 얻으면 fail-closed: `ok=False`와 사유를 반환한다.

2. 인식 — `posting_recognizer.recognize_posting()`
   - 텍스트 신호가 충분하고 회사·직무가 잡히면 `recognition_mode="text"`.
   - 텍스트가 부족하고 근거 이미지가 있으면 주입형 `vision_analyzer`(운영 시 Claude 비전 호출)를 불러 `recognition_mode="vision"`으로 회사/직무/confidence를 채운다.
   - 둘 다 부족하면 `recognition_mode="none"`, 낮은 confidence, "insufficient signal" 사유.
   - confidence는 정직하게 보고하고, 등록 게이트는 핸들러가 `is_job_posting and confidence>=threshold`(기본 0.55)로 판단한다. 게이트 탈락 시 등록하지 않고 "원문 확인 요청" 사유로 skipped.

3. 중복 판정 — `position_dedup.find_duplicate_position()`
   - 주입형 `clickup_search(recognition)`로 기존 `ExistingPositionTask` 목록을 받는다.
   - canonical source_url 일치를 먼저 보고, 없으면 `normalize_company` 동일 AND `normalize_role` 동일로 매칭한다.

4. 반영 — `run_position_registration()` 분기
   - 중복 있음: `dry_run`이면 `status="linked"`/`is_new_task=False`로 계획만 산출(쓰기 호출 안 함). 실제 실행이면 `clickup_create_comment(task_id, body)`로 근거 댓글을 달고 `comment_id`를 보고한다.
   - 중복 없음: `dry_run`이면 `status="created"`/`is_new_task=True` 계획만 산출. 실제 실행이면 `clickup_create_task(title, body)`로 새 포지션 태스크를 만들고 `task_id`/`task_url`을 보고한다.
   - 태스크 제목은 `build_task_title()`(`{company} - {role}`), 본문은 `build_registration_body()`(JD 요약 + 원본 URL + 추출/이미지 근거 경로, 시크릿 비포함).
   - 결과(`RegistrationOutcome`)는 항상 `external_posting_sent=False`, `secret_emitted=False`이며 `recognition_mode`/`confidence`를 함께 싣는다.

## Discord 챗봇 구현 기준

### 파서/접근
- 파서 위치: `tools/multi_position_sourcing/request_parser.py`
- 등록 파서: `parse_discord_position_registration_request()`
- 검색 파서: `parse_discord_search_request()`
- 등록 요청은 `parse_discord_search_request()`에서 `should_route_to_search=False`가 되어야 한다.
- 접근 제어는 `tools/multi_position_sourcing/access.py`의 `discord_dm_routing_guard()`를 재사용한다.

### 실행 계층
- 데이터 계약: `tools/multi_position_sourcing/posting_models.py` (frozen dataclass — `FetchResult`, `ExtractedPosting`, `VisionAnalysis`, `PostingRecognition`, `ExistingPositionTask`, `DuplicateMatch`, `RegistrationOutcome`). 모든 실행 모듈이 여기서 타입을 가져온다.
- 추출: `tools/multi_position_sourcing/posting_extractor.py` (httpx 우선 → Playwright 폴백, 표준 라이브러리 HTML 파싱, 근거 이미지 저장).
- 인식: `tools/multi_position_sourcing/posting_recognizer.py` (텍스트 인식 → 부족 시 Claude 비전 vision_analyzer 주입 호출, confidence 게이트).
- 중복: `tools/multi_position_sourcing/position_dedup.py` (source_url 또는 회사+직무 정규화 일치).
- 오케스트레이션: `tools/multi_position_sourcing/position_registration.py` (`run_position_registration()`, `dry_run` 기본 True).
- 순수 모듈은 stdlib만 임포트한다. 네트워크/브라우저는 모듈 본문이 아니라 함수 내부 lazy import로만 다룬다(테스트는 fake 주입).
- ClickUp 쓰기는 런타임에 MCP clickup 도구로 수행하며, `run_position_registration()`에 주입하는 `clickup_search`/`clickup_create_task`/`clickup_create_comment` 콜러블을 통해 연결한다. `dry_run=True`(기본)에서는 이 콜러블을 호출하지 않고 계획만 산출한다.

## 검증 명령

pytest는 이 환경에 없다(PEP 668). 테스트는 unittest 기반이며 다음으로 실행한다.

```bash
python3 -m unittest tests.test_multi_position_sourcing
python3 -m unittest tests.test_posting_extractor tests.test_posting_recognizer tests.test_position_dedup tests.test_position_registration
```

## 보고 형식

짧게 다음을 보고한다.

- 등록/연결 결과
- 새 태스크 생성 여부
- ClickUp 태스크 URL/ID
- 댓글 ID 또는 검증 근거
- 외부 게시/메일 발송을 하지 않았다는 점
