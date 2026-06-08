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

1. 입력 정리
   - URL 또는 JD 본문을 추출한다.
   - Wanted URL이면 HTML 메타데이터에서 회사명/포지션명/JD 텍스트를 가능한 범위에서 읽는다.

2. 기존 ClickUp 태스크 검색
   - FY26ClientsPosition 리스트에서 회사명/포지션명/Wanted URL 기준으로 기존 태스크를 찾는다.
   - 기존 태스크가 있으면 새로 만들지 않는다.

3. 반영
   - 기존 태스크가 있으면 원본 URL/JD 근거 댓글을 단다.
   - 기존 태스크가 없고 입력이 충분하면 새 포지션 태스크를 만든다.
   - 입력이 부족하면 생성하지 않고 필요한 입력을 요청한다.

4. 검증
   - ClickUp API로 태스크 또는 댓글을 다시 조회한다.
   - 보고에는 태스크 ID, 태스크 URL, 댓글 ID, 중복 생성 여부를 포함한다.

## Discord 챗봇 구현 기준

- 파서 위치: `tools/multi_position_sourcing/request_parser.py`
- 등록 파서: `parse_discord_position_registration_request()`
- 검색 파서: `parse_discord_search_request()`
- 등록 요청은 `parse_discord_search_request()`에서 `should_route_to_search=False`가 되어야 한다.
- 접근 제어는 `tools/multi_position_sourcing/access.py`의 `discord_dm_routing_guard()`를 재사용한다.

## 검증 명령

```bash
python3 -m pytest tests/test_multi_position_sourcing.py::MultiPositionSourcingTests::test_discord_position_registration_request_takes_precedence_over_search -q
python3 -m pytest tests/test_multi_position_sourcing.py -q
```

## 보고 형식

짧게 다음을 보고한다.

- 등록/연결 결과
- 새 태스크 생성 여부
- ClickUp 태스크 URL/ID
- 댓글 ID 또는 검증 근거
- 외부 게시/메일 발송을 하지 않았다는 점
