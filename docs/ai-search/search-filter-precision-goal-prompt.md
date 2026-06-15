# Goal Prompt: 포털 검색 필터 정교화 (연차·업종·직무 일치성)

대상: Valuehire AI Search 포털 검색 로직(`scripts/run_portal_search.py`, `scripts/collect_linkedin.py`, `scripts/score_moorgen.py`, `tools/multi_position_sourcing/*`). 브라우저 제어 표준은 Playwright. 검색·수집까지만, 외부 발송 금지, 캡차/2FA 우회 금지.

```text
Goal:
사람인·잡코리아·LinkedIn RPS 검색을, JD에서 발라낸 직무·업종·연차 조건으로 "최적합 인재만" 정확히 소팅되도록 필터를 정교화한다. 검색 화면에 이미 세팅된 필터 값이 있어도 그것에 의존하지 말고, AND/OR 키워드 조건을 매 검색마다 초기화한 뒤 이 포지션에 맞는 키워드로 새로 세팅하는 것이 가장 중요하다.

Context:
- 포지션 스펙(JD)에서 다음을 추출해 검색 스펙으로 만든다: 직무(타이틀 동의어), 업종/도메인, 연차, 지역, 타겟 출신사, 제외 조건.
- 한국어와 영어 키워드를 둘 다 사용해 한쪽 언어로만 검색해 놓치는 인재가 없게 한다.
- 현재 구현은 키워드 1개만 넣고 연차·학력·지역·업종 facet을 적용하지 않으며, 결과카드 셀렉터도 라이브 DOM과 일부 불일치한다.
- SOT: docs/search-access.md, docs/ai-search/browser-control-methods-comparison-2026-06-09.md, docs/ai-search/portal-search-runbook-2026-06-15.md

공통 원칙 (전 채널):
1. 검색 실행 전, 화면에 남아있는 기존 AND/OR/NOT 키워드 값을 **모두 초기화(clear)** 한다. 이전 검색의 잔여 필터가 결과를 오염시키지 않게 한다.
2. AND/OR/NOT에 들어갈 키워드를 이 포지션 기준으로 **새로 세팅**하는 것이 최우선 작업이다.
3. 키워드는 **한국어 + 영어** 동의어를 함께 구성한다. (예: 영업/세일즈/Sales/Business Development/Account)
4. 연차는 JD 기준 **±1~2년 폭**으로 넓게 잡아도 된다. (예: JD 3~10년 → 검색 2~12년)
5. **이직이 잦은(짧은 재직 반복) 후보**와 **Freelancer/Freelance로 현재 상태가 표기된 후보**는 프로필을 패스(제외 또는 최하위)한다.
6. 직무·업종·연차 일치성을 결과 카드/프로필 텍스트에서 파싱해 점수화한다. 본문 미열람 항목은 risk로 표시한다.

사람인 (Talent Pool):
- OR(`input.search_input`): 직무 동의어 (한/영). 기존 OR 값 전부 삭제 후 재입력.
- AND(`input.search_input.result`): 업종/도메인 핵심어 (한/영). 기존 AND 값 전부 삭제 후 재입력.
- NOT: 제외 업종/직무 (예: 보험·자동차·순수개발).
- 연차: `#career_min`/`#career_max`를 JD±1~2년으로 설정.
- 학력/기업규모/국내 유명대학 태그는 JD가 요구할 때만.
- 결과카드 셀렉터(`RESULT_CARD_SELECTORS["saramin"]`)를 라이브 DOM에 맞게 보강한다(회원가입 등 비후보 링크 오탐 제거).

잡코리아 (Corp/Person/Find):
- 통합검색 `#txtKeyword`: 직무+업종 키워드 (한/영). 매 검색 전 입력값 초기화.
- 지역 `#txtWorkingAreaKeyword`: 서울/수도권(JD 근무지 기준).
- 학력 `#education1`(대학교4년) 등 JD 요구 시.
- 연차 `#txtCareerStart`/`#txtCareerEnd`: JD±1~2년.
- 결과카드 셀렉터(`RESULT_CARD_SELECTORS["jobkorea"]`)를 라이브 DOM에 맞게 보강.

LinkedIn RPS (가장 중요: Boolean):
- **Keywords Boolean 세팅이 1순위.** JD에서 핵심 키워드를 발라내고, 상위 인재가 프로필에 실제로 적을 법한 표현으로 Boolean을 가장 적확하게 조합한다.
  - 형식 예: (직무 OR 동의어) AND (타겟사 OR 도메인) — 한/영 혼용.
  - 예: ("Sales" OR "Business Development" OR "Account Manager" OR 영업) AND ("Smart Home" OR "Home Automation" OR KNX OR DALI OR "Lighting Control" OR Crestron OR Lutron OR Somfy OR Legrand OR Signify OR Schneider)
- **2순위: Years of Experience** facet을 JD±1~2년으로.
- Location=South Korea, Open to Work 우선 신호.
- 수집은 lazy-load이므로 5초 대기 + 스크롤 후 `a[href*="/talent/profile/"]`.
- 이직 잦은/Freelancer 프로필은 패스.

해야 할 일:
1. JD → 검색 스펙(직무·업종·연차·지역·타겟사·제외)을 한/영으로 구조화한다(공유 스펙 파일).
2. 각 채널 러너에 "기존 AND/OR/NOT 초기화 → 포지션 키워드 재세팅 → 연차/지역/학력 필터 적용" 로직을 구현한다.
3. LinkedIn은 Boolean 문자열 빌더를 만들어 keywords facet에 정확히 주입하고, YoE facet을 적용한다.
4. 사람인·잡코리아 결과카드 셀렉터를 보강해 실후보만 수집한다.
5. 이직 잦은/Freelancer 후보 패스 규칙을 스코어러에 반영한다.
6. 한/영 키워드 모두로 검색해 합집합·중복제거한 롱리스트를 산출한다.

안전 규칙:
- 토큰/비밀번호/쿠키는 출력 금지([REDACTED]).
- 캡차/2FA/보안문자/checkpoint는 우회하지 않는다. 감지 시 멈추고 사람 호출.
- 외부 발송(후보 컨택/InMail/이메일)은 하지 않는다. 검색·수집까지만.
- 기존 로그인 프로필을 재사용하고, 작업 후 headed 창은 닫아 머신을 점유하지 않는다.

Expected final answer:
한국어로 보고한다. "구현 완료/미완료", "채널별 재수집 결과(연차·업종·직무 일치 후보 수)", "남은 조치"를 구분해서 말한다.
```

## 짧은 버전

```text
Goal:
사람인·잡코리아·LinkedIn 검색을 JD 기반 직무·업종·연차 키워드로 정교화한다.

핵심 규칙:
- 사람인/잡코리아: 화면에 남은 AND/OR/NOT 값을 매 검색 전 전부 초기화하고, 이 포지션 키워드로 새로 세팅(이게 가장 중요). 한국어+영어 동의어 둘 다 사용.
- 연차: JD ±1~2년 폭으로.
- 이직 잦은 후보, Freelancer는 프로필 패스.
- LinkedIn: Keywords Boolean 세팅이 1순위(JD 핵심어를 발라 상위 인재가 적을 표현으로 적확히 조합), 2순위 Years of Experience. Location=South Korea, Open to Work 우선.
- 결과카드 셀렉터 보강(사람인/잡코리아), lazy-load 스크롤(LinkedIn).

Safety: 캡차/2FA 우회 금지, 외부 발송 금지(검색·수집만), 비밀값 출력 금지, 프로필 재사용 후 창 닫기.
```
