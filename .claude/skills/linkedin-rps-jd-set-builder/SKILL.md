---
name: linkedin-rps-jd-set-builder
description: LinkedIn Recruiter(RPS)에서 한 포지션의 InMail 본문(개요식 인사 + 회사 브리핑 + JD 핵심 + 설득 포인트 + 간결한 클로징)을 1,899자 이내로 작성하고, AI Touch up 자동작성을 무시한 채 신규는 "Save as new", 정정은 기존 템플릿 "Update current"로 저장/수정까지 한 턴에 처리. 발송(Send)은 절대 자동으로 누르지 않음 — 사장님 수동 발송 게이트. 어제(2026-05-22) jd-set-builder design spec 의 LinkedIn 1채널을 SKILL 로 실현. 트리거 키워드 — "jd builder", "JD 빌더", "jd 빌더", "jdbuilder", "JD 셋", "JD set", "JD set builder", "JD 셋 빌더", "제안 본문 만들어", "링크드인 JD 셋", "LinkedIn JD set 빌더", "LinkedIn InMail 템플릿 등록", "linkedin-rps-jd-set", "RPS 템플릿 만들어", "링크드인 포지션 등록", "Save as new 템플릿". ⚠️ **"jd builder" = 사장님 통합 단축어** — 채널은 상황에 맞게 라우팅: LinkedIn InMail=본 스킬, 사람인=`saramin-talent-sourcing`, 잡코리아=`jobkorea-talent-sourcing`, 채용공고 게시=`recruit-post-builder`. 모든 채널 공통 §6 회사 브리핑 7요소(R20) 적용.
---

# LinkedIn RPS — JD Set Builder (InMail 템플릿 한 턴 워크플로우)

> 2026-05-23 사장님 명시 — `docs/superpowers/specs/2026-05-22-jd-set-builder-design.md` 의 LinkedIn 1채널을 SKILL 로 실현. 어제 디자인한 4채널(사람인/잡코리아/InMail/메시지) 중 **LinkedIn InMail 템플릿 저장 자동화**만 1차로 명문화. 사람인/잡코리아 SKILL R9 와 동일하게 회사 리서치는 jd_sets 캐시를 우선 사용.

---

## 0. 절대 규칙 (사장님 명시 — 절대 위반 금지)

| # | 규칙 | 근거 |
|---|------|------|
| R0 | **Send 버튼 절대 자동 click 금지 — Save template 까지만** | InMail 발송 = 차감 + 후보자 노출. 되돌릴 수 없는 액션. 사장님 수동 발송 게이트(2026-05-23 명시) |
| R1 | **AI Touch up auto-draft 무시 — "Got it" 또는 X 닫기** | "Touch up failed. This feature is only available in English" 영문 한정 + 한국어 톤 망가짐. 사장님 영어 안내 X 닫음 |
| R2 | **본문 총 1,899자 이내 (한국어 + 영어 문자수 합)** | LinkedIn InMail 실무 한도. UI counter는 1,900까지 보이지만 direct composer는 공백/제어문자 차이와 변수 검증 때문에 1,899를 hard cap으로 둔다. 풍성한 본문은 1,800~1,899자를 목표로 하되 모든 길이는 근거 있는 JD/회사 맥락으로 채운다. |
| R3 | **자격증명·세션은 사장님 chrome(:9222) 세션 의존** | LinkedIn 별도 로그인 자동화 금지(2FA·계정 잠금 위험). SKILL 평문 ID/PW 금지 |
| R4 | **사람 개입 시 자동화 즉시 정지** | 사장님이 chrome 만지거나 "내가 할께" 신호 → 모든 자동화 action 0. 메모리 `[[feedback_human_intervention_pause]]` |
| R5 | **봇 검출(캡차/차단/2FA) 즉시 STOP** | 재시도 금지 — RPS 계정 잠금 위험. 디스코드 `OPS_INCIDENTS` 알림 후 사장님 수동 풀이 |
| R6 | **회사 리서치는 AI 생성 — 사장님 검토 전 발송 금지** | `[[project_jd_set_builder_2026_05_22]]` — 매출/투자/연혁 hallucination 위험. 본문 저장 후 사장님 1차 검토 필수 |
| R7 | **회사 매출/투자/인원 수치는 출처가 있는 것만 인용 — 추측 금지** | `companies.research[*].source_url` 또는 사장님이 직접 입력한 값만 사용 |
| R8 | **JD 원본 훼손 금지 — 어투 조정만, 책임 범위·자격요건은 그대로 압축** | 사장님 명시(2026-05-23) "원본 훼손이 있어서는 안됨" |
| R9 | **AI Search direct RPS subject = `[포지션]회사명, 포지션명`** | Codebox/ZUZU 2026-06-23 direct composer Golden Sample 기준. 후보자에게 보낼 직접 RPS/JD 템플릿 subject와 one-off template name은 `[포지션]회사명, 포지션명`로 맞춘다. legacy bulk 내부 template name만 명시 승인 시 `회사명, 포지션명_revN`를 허용한다. |
| R10 | **한국어 textarea 입력은 clipboard + cmd+v + 검증 패턴** | 사람인/잡코리아 SKILL R9~R13 동일. 자모 분리("뤼튼" → "뒤튼") 위험 — `navigator.clipboard.writeText` + `cmd+v` + textarea value 검증 |
| R11 | **신규 생성은 "Save as new", 정정 작업은 기존 템플릿 수정 우선** | 첫 생성은 기존 템플릿 보호를 위해 Save as new. 단, 사장님이 "삭제가 안되니 기존 버전 모두 수정"처럼 명시하면 같은 subject/template name을 먼저 검색해 기존 저장본을 열고 Update current로 교체한다. 템플릿 정체성이 화면에 보이지 않으면 수정 금지. |
| R12 | **템플릿 visible = "Anyone in my organization" 라디오 명시 클릭 + selected 검증** | 사장님 명시 (2026-05-23 + 2026-05-25 재강조 스크린샷) — 다음 헤드헌터(향후 합류 인원)가 재활용. "Only me" 변경 금지. 디폴트 신뢰 금지 — 매 저장 시 라디오 click 후 `aria-checked="true"` 또는 input.checked 확인 |
| R13 | **저장 후 미리보기 캡처 → 사장님 Discord 송부 + 사장님 OK 받기 전 Send 금지** | 사람인/잡코리아 SKILL R12 동일 패턴. 미리보기 = `Preview` 버튼 click 후 새 창/모달 화면 캡처 |
| R14 | **자동화는 한 번에 1개 후보자 프로필 한정 — bulk *발송* 금지** | RPS bulk 발송 = LinkedIn 정책 위반 + 계정 정지. 사장님 직접 발송 흐름 보조만 |
| R15 | **Bulk *템플릿 저장*은 §16 Rate Limit 준수 시 허용** | 발송이 아닌 템플릿 저장은 차감 0 + 발송 0. 단 §16 규정(1포지션당 60초+, **25건 회차 5분 휴식**, 90분 최대, 하루 30건) 절대 준수. 사장님 명시(2026-05-23 "너무 빨리하지 마라" + 2026-05-25 "25건×3회차") |
| R16 | **position-batch orchestrator 통합** | `tools/position-batch/orchestrator.mjs` 의 [4] RPS Save 단계가 본 SKILL §16 을 25건×3회차로 분할 호출. 결과는 Supabase `position_batch_steps` 의 `step='rps_save'` 로 적재 + chrome-guard 매 회차 시작 전 체크. 자세한 흐름: [[2026-05-25-position-batch-orchestrator-design]] §5[4] |
| **R20** | **🔥 도입부 회사 브리핑 8요소 필수 — 요소 스펙 SOT = `position-register` §1.5 (2026-07-02 상향: 기존 7요소 + ⑥모기업/계열, 6요소 미만이면 저장 전 보고). 빠지면 본문 미완성으로 간주, 발송/저장 금지** — 상단에 ⑴회사명 ⑵연혁 ⑶대표 소개 ⑷투자 단계 ⑸매출 ⑹인원 ⑺주요 뉴스 를 반드시 브리핑. §6.1 단②·§6.2 템플릿 참조. **사장님 명시 "100번 이야기했다"(2026-05-30) + 2026-05-23 "회사 소개가 상당히 약하네" + 2026-05-22 "재무·투자·뉴스·인원·매출·제품·임원뉴스·아웃스탠딩 다 넣어라".** R7 출처-only(추측 금지). JD 본문만 덜렁 붙이는 것 절대 금지. 4채널(사람인/잡코리아/InMail/이메일) 공통 적용 | 사장님 반복 명시 — 가장 자주 빠뜨린 규칙 |
| **R21** | **🎯 본문 맺음 인입 CTA 1줄 필수** — 서명(강상모 드림) 뒤 구분선 + `P.S. 지금 이 포지션이 딱 맞지 않으셔도 괜찮습니다. 밸류커넥트가 이력서를 직접 검증해, 더 잘 맞는 기회까지 연결해 드립니다 — 무료 커리어 검증 신청: https://valuehire.cc/resume`. 후보자를 0원 검증 깔때기(VERIFIED-PULL)로 자연 인입. §6 ⑤ 참조. 4채널 공통. **매칭 우선권 무관한 정보성 안내로만(취업 알선 대가·합격보장 표현 금지).** 링크 라이브 `/resume`(배포 후 `/career` 검토). | 사장님 명시 2026-05-30 (push-bodies 하단 인입 링크) |
| **R22** | **Golden Sample 빠른 경로: local artifact -> DOM inventory -> fill -> org radio evidence -> save toast**. Codebox/ZUZU 2026-06-23 run에서 가장 오래 걸린 병목은 문안이 아니라 브라우저 상태/DOM/라디오 검증이었다. 직접 composer에는 raw `{{...}}` 변수를 붙이지 말고, 저장 전 `Only me=false` + `Anyone in my organization=true`를 DOM과 스크린샷으로 모두 증명한다. | 2026-06-23 live run + Claude adversarial FAIL remediation |
| **R23** | **문안은 개요식 + 5원칙 균형 분할**. 축약하더라도 빈약하면 실패다. 글자 수를 늘리는 어투는 줄이고, 회사 사실/조직·원칙/JD/자격·우대/설득 포인트/CTA를 짧은 bullet로 나눈다. Codebox/ZUZU처럼 5원칙이 있는 회사는 한 줄 나열 금지, 5개 bullet로 균형 배치한다. `지원 요청이 아닙니다`, `30분`, `브리핑`, `[근무/절차]`, `[근무/다음]`은 기본 생성 금지다. 근무/절차/레퍼런스 정보는 JD상 핵심 설득 정보일 때만 1개 짧은 fact bullet로 넣는다. `밸류커넥트(valueconnect.kr)`와 요청 시 `Valuehire.cc` 개인정보 동의/Subscription 안내를 포함한다. | 2026-06-23 사장님 피드백 |
| **R24** | **2026-06-23 Target-company save lessons 고정**. Chrome 탭이 많을 때 full Playwright `connectOverCDP`는 느리거나 멈출 수 있으므로 exact LinkedIn page target raw CDP를 우선한다. 새 템플릿은 기존 선택 템플릿을 먼저 clear한 뒤 subject/body를 채우고 `Save as new template`로 저장한다. multi-line Korean body가 첫 문단만 들어가면 line-by-line `insertLineBreak` + `insertText`로 재입력한다. 기존 템플릿 검색은 option/listbox row로만 제한하고 broad DOM text click 금지. `Save message template` popover 안의 작은 Save만 클릭한다. legacy `_rev1` 저장 러너 사용 금지. Long batch에서 같은 control이 두 번 이상 꼬이면 stale tab과 싸우지 말고 fresh authenticated `rightRail=composer` target을 열어 save-log skip set으로 이어간다. | 2026-06-23 5-company live save remediation |
| **R25** | **raw brace / HTML comment 금지**. Direct RPS composer는 raw `{{...}}`뿐 아니라 스크래퍼 메타데이터 `<!-- integrity: {"source":"..."} -->` 같은 braces도 invalid variable banner로 볼 수 있다. 브라우저 입력 전 HTML comment, `{`, `}`, zero-width emoji marker를 제거하고 validator에 박는다. | 2026-06-23 AX Frontend invalid-variable stop |
| **R26** | **AI Search 내장 레인**. 이 스킬은 AI Search 이후 별도 요청이 있을 때만 부르는 부록이 아니다. 신규/현재 포지션 AI Search에서는 `LinkedIn/RPS JD 템플릿` 산출물로 항상 상태가 보고돼야 한다. 브라우저 저장까지 가능하면 `saved/updated`, 불가능하면 `local-package-only` 또는 `blocked(사유)`로 남긴다. 로컬 패키지만 만든 상태를 저장 완료로 말하지 않는다. | 2026-06-23 Golden Sample process embedding |

---

## 1. 환경 준비

```bash
# (a) Chrome 디버그 모드 (이미 떠 있으면 skip)
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --remote-debugging-port=9222 --user-data-dir=/tmp/chrome-debug &

# (b) MCP claude-in-chrome 1순위 — 사장님 LinkedIn 로그인 세션 그대로 활용
# (c) Playwright connectOverCDP 는 fallback

# (d) LinkedIn 계정 라이선스 확인
#  - Value Connect Recruiter 계정 필수 (일반 LinkedIn 계정 X)
#  - Recruiter Lite 가 아니라 Recruiter Corporate 권장 (InMail 50+/월)
```

**도구 선택:**
- 1순위: `mcp__claude-in-chrome__*` — 사장님 LinkedIn 세션 그대로 사용
- 2순위: `playwright-core` + `connectOverCDP("http://localhost:9222")` — fallback

---

## 1A. Golden Sample Fast Path — AI Search 내장 후보자 JD 작성/저장

Codebox/ZUZU 2026-06-23 라이브 run에서 검증된 단축 경로. 이후 AI Search에서 후보자에게 보낼 JD/InMail 템플릿을 만들 때 이 순서를 먼저 따른다. 신규/현재 포지션 AI Search에서는 이 단계가 별도 사후 작업이 아니라 기본 산출물 레인이다.
DOM/브라우저 증거의 상위 SOT는 `/Users/kangsangmo/Desktop/Valuehire_v4/docs/sot/23-channel-dom-selectors.md`다.

1. **로컬 산출물부터 만든다.** 브라우저에 바로 쓰지 말고 JSONL/preview/source_notes/validator를 먼저 만든다. direct composer용 본문은 기본 1,600~1,899자, 사장님이 "1899자에 가깝게/풍성하게"라고 하면 1,800~1,899자, raw `{{...}}` 변수 0개, raw brace/HTML comment 0개, markdown wrapper 0개, emoji 0개, 회사 채용페이지 직접지원 CTA 0개.
2. **JD 원문과 현재 웹 채용정보를 먼저 비교한다.** 회사 수치, 직무 책임, 기술 스택, 우대사항, 근무조건은 source_notes에 URL/파일 근거를 남긴다. 공개 JD가 있으면 공개 JD를 우선하고, 내부 target evidence는 보조로만 쓴다.
3. **문안은 개요식으로 짠다.** 긴 수식어를 줄이고 `[회사]`, `[일하는 방식 5원칙]`, `[포지션 핵심]`, `[왜 검토할 만한가]`, `[자격/우대]`, `[클로징]`처럼 나눈다. 5원칙은 한 줄 압축 금지, 5개 bullet로 균형 분할한다. 가능하면 `밸류커넥트`를 `valueconnect.kr`로 hyperlink하고, 불가하면 `밸류커넥트(valueconnect.kr)`로 쓴다.
4. **브라우저는 사장님 Chrome `:9222`를 공유 작업장으로 취급한다.** 로그인 세션은 재사용하되, 사장님이 동시에 브라우저를 쓰면 click/text mutation은 즉시 멈춘다. read-only screenshot/DOM inspection만 허용한다. Chrome 탭이 많으면 full-browser attach 대신 exact `linkedin.com/talent/...rightRail=composer` page target raw CDP로 붙는다.
5. **오래된 composer와 discard prompt는 오염 상태로 본다.** 안전하게 닫을 수 있다는 근거가 없으면 싸우지 말고 fresh Recruiter right-rail profile target을 연다. 메시지 draft를 임의 폐기하지 않는다.
6. **selector-first 금지, DOM inventory-first.** 먼저 visible buttons/links, subject input, editor/contenteditable, save-template control, popover input, radio labels/state, error banner, counter, Send button을 dump한다. 그 뒤 role/text/index로 액션한다.
7. **기존 버전 정정이면 새로 만들지 않는다.** 같은 subject/template name을 먼저 검색한다. 기존 템플릿이 확인되면 body를 교체하고 Update current를 사용한다. first creation이거나 사장님이 새 저장을 승인한 경우에만 `Save as new template`을 쓴다. 검색 결과 선택은 실제 option/listbox row로만 제한한다. broad DOM text scan은 현재 composer 본문을 잘못 클릭해 `Replace content?` 모달을 만들 수 있으므로 금지한다.
7-1. **신규 저장은 선택 템플릿 clear부터 시작한다.** 기존 템플릿이 선택된 상태면 먼저 clear하고, subject/body를 채운 뒤 `Save as new template` 버튼이 보이는 상태에서 저장한다. Current UI는 별도 `Message template name` input이 나타날 수도 있다. 보이면 반드시 exact subject를 채운다. 비어 있으면 Save를 눌러도 validation error만 난다.
8. **저장 전 증거를 남긴다.** subject exact, body counter <= 1,899, invalid-variable banner 0, raw brace variable 0을 확인한다. visibility control이 보이면 `Anyone in my organization`을 명시 선택한다.
9. **조직공유 라디오는 양방향으로 검증한다.** `Only me` unchecked + `Anyone in my organization` checked를 DOM으로 확인하고, 같은 순간의 pre-save/update screenshot을 저장한다. Save/Update 후 exact template-name success toast screenshot을 저장한다. Toast가 DOM에 남지 않으면 popover close, org radio state, counter, invalid-banner absence, Send-not-clicked evidence를 JSON log로 남기고 가능하면 exact option search로 후검증한다. Send는 절대 누르지 않는다.
9-1. **입력 실패 fallback.** long Korean body는 `Input.insertText`를 피한다. `execCommand('insertText', false, body)`가 첫 문단만 넣으면 `String.fromCharCode(10)`으로 줄을 나누고 `insertLineBreak` + `insertText`를 반복한다. raw CDP `Runtime.evaluate` 안에서는 regex literal, optional chaining, `${...}` template interpolation을 피한다. Runtime/evaluate가 느려지거나 같은 tab에서 search dropdown/save popover가 반복적으로 남으면 fresh target으로 갈아타고 save-log 기준으로 이어간다.
10. **적대검증은 화면 증거까지 공격한다.** Claude에게 "스크린샷이 정말 organization-visible을 증명하는가"를 물어보고, Codex/Claude 본체가 Claude 판정을 다시 DOM/screenshot으로 재현한다.

---

## 2. 트리거 입력 (사장님 명령 패턴)

3가지 트리거 패턴 모두 동일 흐름으로 수렴:

| 패턴 | 입력 예시 | SKILL 행동 |
|------|----------|----------|
| **A. 후보자 URL + 포지션** | "이 프로필에 뤼튼 AX PM 템플릿 등록해줘 — https://www.linkedin.com/talent/hire/.../profile/AEMAAD..." | 해당 프로필 페이지로 진입 → 즉시 §3 시작 |
| **B. 회사·포지션만 (프로필 미지정)** | "뤼튼 AX PM 으로 LinkedIn JD Set 만들어줘" | jd_sets 캐시 + companies.research 조회 → 본문만 생성하고 사장님께 "어느 프로필에 등록할까요?" 1회 확인 |
| **C. 사람인/잡코리아 R9 cascade** | 사람인/잡코리아 SKILL 진행 중 "LinkedIn 채널도 함께" | jd_sets.channels.linkedin_inmail.body 재활용 (재생성 0) |

⚠️ **본 SKILL 은 "프로필이 있어도 자동 발송하지 않음"** — 본문 입력 → 템플릿 저장까지만. 발송(Send) 누름은 사장님 수동.

---

## 3. 프로필 페이지 진입 (트리거 A·B 공통)

### 3.1 진입 URL 패턴

LinkedIn Recruiter 후보자 프로필 페이지 (예시 — 사장님 화면):

```
https://www.linkedin.com/talent/hire/{projectId}/discover/recruiterSearch/profile/{candidateId}/messages
  ?project={projectId}
  &rightRail=composer
  &searchContextId=...
  &searchHistoryId=...
  &searchRequestId=...
```

핵심 식별자:
- `projectId` (URL path 1번째 segment) — 예: `1670911580`
- `candidateId` (path `/profile/{...}`) — 예: `AEMAADKEVfcBS_y8yKAQh0oYzgPcfpYnCzaW0sU`

### 3.2 진입 + 메시지 패널 노출

```javascript
// 1. mcp__claude-in-chrome__navigate 로 URL 진입
// 2. wait 5초 (LinkedIn lazy load — 사이드바·composer 둘 다 로드)
// 3. 우측 "Compose Message" 패널 노출 검증:
const composeOpen = !!document.querySelector('[data-test-id="composer"], .composer, [class*="ComposeMessage"]');
if (!composeOpen) {
  // composer 미노출 → InMail 아이콘(✉) click
  document.querySelector('button[aria-label*="message" i], button[aria-label*="InMail" i]')?.click();
}
```

### 3.3 사이드바 후보자 메타데이터 캡처 (개인화 인사 재료)

`section[data-test-profile-card]` 또는 좌측 sidebar 에서 다음 6종 추출:

```javascript
const meta = {
  name:         document.querySelector('[data-test-row-lockup-full-name], h1')?.innerText?.trim(),
  headline:     document.querySelector('[data-test-row-lockup-headline]')?.innerText?.trim(),
  currentCo:    document.querySelector('[data-test-current-company]')?.innerText?.trim(),
  currentRole:  document.querySelector('[data-test-current-position]')?.innerText?.trim(),
  school:       document.querySelector('[data-test-education-school]')?.innerText?.trim(),
  location:     document.querySelector('[data-test-location]')?.innerText?.trim(),
};
```

⚠️ 위 selector 는 LinkedIn 가 분기 단위로 바꿈 → 실패 시 텍스트 전체 dump 후 LLM 1턴 추출 폴백.

---

## 4. AI Touch up 자동작성 무시 (R1)

LinkedIn Recruiter 의 "AI Touch up auto-draft" 패널은 영어 한정 + 한국어 톤 망가뜨림:

```
"AI Touch up auto-draft is enabled
 AI-assisted messages can improve InMail accept rate by 40%..."
 [Got it] [View settings]                                  [X]
```

자동 대응:
```javascript
// 1순위: [Got it] click — 패널 닫힘
document.querySelector('button[aria-label*="Got it"], button:contains("Got it")')?.click();

// 2순위: [X] close 아이콘 click
document.querySelector('button[aria-label="Dismiss"], button[aria-label="Close"][class*="touch"]')?.click();

// 3순위: View settings 무시 (열면 사장님 계정 설정 영향 — 절대 click 금지)
```

검증: 패널 닫혀야 textarea 가 노출됨.

⚠️ "Touch up failed. This feature is only available in English." 에러 토스트가 떠도 무시. 본 SKILL 은 한국어 본문 전용.

---

## 5. 제목(Subject) 입력 (R9)

### 5.1 제목 컨벤션

| 채널 | 제목 패턴 | 예시 |
|------|----------|------|
| LinkedIn InMail direct / AI Search Golden Sample | `[포지션]회사명, 포지션명` | `[포지션]뤼튼테크놀로지스, AX PM` |
| LinkedIn bulk 내부 template name (명시 승인 시만) | `회사명, 포지션명_revN` | `뤼튼테크놀로지스, AX PM_rev1` |
| 사람인 이직제안 | 제목 영역 없음 (포지션 선택으로 대체) | — |
| 잡코리아 이직제안 | 제목 영역 없음 (포지션 선택으로 대체) | — |
| 클릭업 task name | `[회사명] 포지션명` | `[뤼튼] AX Product Manager` |

핵심: AI Search direct RPS는 `[포지션]회사명, 포지션명`로 통일해 후보자/포지션 검색 회수가 가능해야 한다. 사람인/잡코리아/ClickUp은 각 채널 SOT 제목 규칙을 따른다.

### 5.2 Subject 입력 (textbox 1줄)

LinkedIn RPS Initial message 영역 상단:
- `Subject:` 또는 검색 박스(돋보기 + placeholder "뤼튼")

```javascript
// (a) Subject input focus
const subject = document.querySelector('input[name="subject"], input[placeholder*="Subject"], input[type="text"][class*="composer"]');
subject.focus();

// (b) value setter 우회 (React controlled input)
const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
setter.call(subject, `[포지션]${COMPANY_SHORT}, ${POSITION_TITLE}`);
subject.dispatchEvent(new Event('input', { bubbles: true }));

// (c) 검증
if (subject.value !== expected) { /* clipboard + cmd+v 폴백 */ }
```

---

## 6. 본문(Initial message) 입력 — 1,899자 개요식 구성 (R2·R8·R23)

### 6.1 본문 구성

총 **1,899자 이내** (공백·줄바꿈 포함, 한국어 + 영어 문자수 합). 풍성하되 산문을 늘리지 말고, 짧은 bullet로 정보 밀도를 높인다.

| 단 | 글자수 가이드 | 내용 |
|----|------------|------|
| **① 인사** | 120~220자 | `안녕하세요!` + `Tech Searchfirm 밸류커넥트(valueconnect.kr)의 강상모` + 포지션 검토 가능 여부. direct composer에는 raw `{{firstName}}` 금지. |
| **② 회사/서비스** | 250~400자 | 회사가 무엇을 하는지, 검증된 임팩트 fact, 고객군/시장 위치. 출처 없는 매출·투자·인원은 쓰지 않는다. |
| **③ 일하는 방식/조직 원칙** | 200~350자 | 회사가 5원칙/values/way를 공개하면 한 줄 나열 금지. 5개 bullet로 균형 분할한다. Codebox/ZUZU는 All-makers, Raise the bar, Less is better, Extra-mile, Growth over excellence를 각각 설명한다. |
| **④ 포지션 핵심** | 450~650자 | 주요 업무 4~6 bullet, 스택, 도메인 난이도, 제품화 기준. 원문 책임 범위는 훼손하지 않는다. |
| **⑤ 왜 검토할 만한가** | 250~400자 | 후보자가 시간을 내야 할 이유: 역할 권한, 제품 난이도, 도메인 매력, 성장/임팩트, 후보자-fit을 2~5 bullet로 쓴다. |
| **⑥ 자격/우대** | 220~350자 | 자격 3~5 bullet, 우대 2~4 bullet. 원문 없는 요건은 만들지 않는다. |
| **⑦ 클로징 + 선택 CTA** | 150~300자 | 근무조건, 레퍼런스/절차는 원문에 있고 설득에 필요한 것만 1개 짧은 bullet. `강상모 드림`, 요청 시 `Valuehire.cc` 개인정보 동의/Subscription 안내를 짧게 포함한다. |

### 6.2 본문 템플릿 (R8 — 원본 훼손 금지)

```
안녕하세요!
저는 Tech Searchfirm 밸류커넥트(valueconnect.kr)의 강상모입니다. {회사명} {포지션명} 포지션을 한 번 검토해보실 수 있을까요?

[{회사명}/{서비스명}]
- {검증된 회사/서비스 한 줄}
- {검증된 임팩트 fact}
- {고객군/시장/제품 맥락}

[일하는 방식 5원칙]
- {원칙1}: {짧은 설명}
- {원칙2}: {짧은 설명}
- {원칙3}: {짧은 설명}
- {원칙4}: {짧은 설명}
- {원칙5}: {짧은 설명}

[포지션 핵심]
- {bullet 1}
- {bullet 2}
- ...

[왜 검토할 만한가]
- {bullet 1}
- ...

[자격/우대]
- {bullet 1}
- ...

[클로징]
- {원문상 꼭 필요한 근무/절차 fact 1개 이하, 없으면 생략}

감사합니다.
강상모 드림

P.S. 밸류커넥트는 Valuehire.cc 서비스를 운영합니다. 후보자님이 개인정보에 동의해주시면 관련 포지션과 커리어 정보를 지속적으로 Subscription 하는 서비스도 제공하고 있습니다. 편히 수락해주셔도 좋겠습니다.
```

### 6.3 1,899자 검증 가드 (R2)

```javascript
const bodyText = textarea.value;
const len = [...bodyText].length;  // 한국어·이모지 정확 count (NFC)
if (len > 1899) {
  throw new Error(`본문 ${len}자 — 1,899자 초과. JD bullet 줄이세요.`);
}
if (len < 1800) {
  console.warn(`본문 ${len}자 — direct RPS Golden Sample 기준 미달. 회사/5원칙/JD/설득 포인트를 개요식으로 보강.`);
}
```

### 6.4 textarea 입력 패턴 (R10 — 자모 분리 우회)

LinkedIn composer 본문은 contenteditable `<div>` 또는 `<textarea>` 양쪽 케이스 모두 존재. 안전 입력 4단:

```javascript
// (1) Editor focus
const editor = document.querySelector(
  '[data-test-id="composer-body"], .composer__body [contenteditable="true"], textarea[name="body"]'
);
editor.focus();

// (2) 기존 내용 전체 선택 → 삭제 (AI Touch up 자동작성 잔재 제거)
document.execCommand('selectAll');
document.execCommand('delete');

// (3) clipboard + execCommand insertText (React 호환 + 한국어 안전)
await navigator.clipboard.writeText(BODY_TEXT);
document.execCommand('insertText', false, BODY_TEXT);

// (4) 검증 — 본문 길이·첫 줄·마지막 줄 모두 일치
const got = editor.innerText || editor.value;
if (![...got].length === [...BODY_TEXT].length) { /* cmd+A → Delete → cmd+v 폴백 */ }
```

⚠️ **사람인/잡코리아 SKILL R9~R13 동일 패턴** — 한국어 escape 금지, execCommand insertText 1순위, JS literal 한국어보다 안정.

---

## 7. 미리보기(Preview) + Discord 송부 (R13)

### 7.1 Preview 버튼 click

본문 입력 후 우하단:
```
[Preview]                                         Free to InMail [i]  [Send]
```

`Preview` click → 모달 또는 우측 패널로 후보자에게 가는 실제 형태 렌더링.

### 7.2 캡처 + Discord embed 송부

```javascript
// (a) Preview 패널 fullPage screenshot
const path = `/tmp/linkedin-jd-set-preview-${candidateId}.png`;
await page.locator('[data-test-id="preview-modal"], [class*="preview"]').screenshot({ path });

// (b) Discord OPS_CANDIDATES 채널 송부 — 사람인/잡코리아 SKILL R12 동일 패턴
await discord.sendEmbed({
  channel: 'OPS_CANDIDATES',
  embeds: [{
    title: `🔍 LinkedIn 발송 직전 미리보기 — ${candidate.name} / ${company} ${position}`,
    url: candidateProfileUrl,             // R11 동일 — embed.url 필수
    description: `**제목**: [${company}] ${position}\n**본문 길이**: ${bodyLen}자\n**개인화 hook**: ${oneLineReason}`,
    image: { url: `attachment://${path}` },
    footer: { text: `candidateId=${candidateId} · LinkedIn InMail · 발송 보류` },
  }],
});

// (c) 사장님 OK 받기 전 Send 금지 (R0)
```

⚠️ R0 — **Discord 송부 후에도 자동 Send 금지**. 본 SKILL 은 항상 Save template 까지만 진행.

---

## 8. 템플릿 저장/수정 — 신규 Save as new, 정정 Update current (R11·R12)

### 8.1 트리거

본문 하단의 `Save template` link click → 작은 popover 모달 노출:

```
┌─────────────────────────────────────┐
│  [ Update current ]  [ Save as new ]│  ← 신규는 Save as new, 정정은 exact 기존 템플릿만 Update
├─────────────────────────────────────┤
│  Save message template              │
│  ┌─────────────────────────────┐    │
│  │ [포지션]{회사명}, {포지션명} │    │
│  └─────────────────────────────┘    │
│                                     │
│  Make this template visible to      │
│   ◯ Only me                         │
│   ⦿ Anyone in my organization       │  ← R12 디폴트 유지
│                                     │
│              [ Cancel ]  [ Save ]   │
└─────────────────────────────────────┘
```

### 8.2 자동화 흐름

R11 분기:
- 신규 생성: `Save as new` 탭을 선택한다.
- 기존 불량 템플릿 정정: 같은 subject/template name을 먼저 검색해 exact match를 로드한다. 화면에 기존 템플릿 정체성이 보이면 `Update current`로 교체한다. exact match가 보이지 않으면 멈추고 DOM/screenshot을 남긴다. 같은 이름의 새 템플릿을 추가하지 않는다.

```javascript
const TEMPLATE_NAME = `[포지션]${COMPANY_NAME}, ${POSITION_TITLE}`;  // 예: "[포지션]뤼튼테크놀로지스, AX PM"

// (1) Save template link click
document.querySelector('a[data-test-id="save-template"], button:contains("Save template")')?.click();

// (2) 신규 생성이면 "Save as new", 정정이면 exact 기존 템플릿 로드 후 "Update current" (R11)
await wait(500);
if (CORRECTION_MODE) {
  if (!document.body.innerText.includes(TEMPLATE_NAME)) {
    throw new Error('exact existing template not visible — do not create duplicate');
  }
  document.querySelector('button[role="tab"][aria-label*="Update current"], [data-test-tab="update-current"]')?.click();
} else {
  document.querySelector('button[role="tab"][aria-label*="Save as new"], [data-test-tab="save-as-new"]')?.click();
}

// (3) 템플릿명 input 채우기/검증
const nameInput = document.querySelector('input[name="templateName"], input[placeholder*="template name" i]');
const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
if (nameInput) {
  setter.call(nameInput, TEMPLATE_NAME);
  nameInput.dispatchEvent(new Event('input', { bubbles: true }));
}

// (4) "Anyone in my organization" radio 검증 — 추정 금지, 양방향 확인 (R12/R22)
const popover = [...document.querySelectorAll('[role="dialog"], [role="menu"], .artdeco-modal, .artdeco-dropdown__content, div')]
  .find(el => /Save message template/i.test(el.innerText || '') && /Make this template visible to/i.test(el.innerText || ''));
if (!popover) throw new Error('Save message template popover not found — dump DOM before continuing');
const radios = [...popover.querySelectorAll('input[type="radio"], [role="radio"]')]
  .map((el, i) => ({
    i,
    el,
    text: (el.closest('label,li,div')?.innerText || el.getAttribute('aria-label') || '').trim(),
    checked: el.checked === true || el.getAttribute('aria-checked') === 'true',
  }));
const org = radios.find(r => /Anyone in my organization/i.test(r.text));
const onlyMe = radios.find(r => /Only me/i.test(r.text));
if (!org || !onlyMe) throw new Error('template visibility radios not found by label — dump popover DOM before clicking Save');
if (!org.checked) org.el.click();
await wait(300);
if (onlyMe && (onlyMe.el.checked === true || onlyMe.el.getAttribute('aria-checked') === 'true')) {
  throw new Error('Only me is still selected — do not Save');
}
if (!(org.el.checked === true || org.el.getAttribute('aria-checked') === 'true')) {
  throw new Error('Anyone in my organization not selected — do not Save');
}
// Take a pre-save/update screenshot here. Codebox/ZUZU 2026-06-23 showed that prose claims can be false.

// (5) [Save]/[Update] button click
document.querySelector('button[type="submit"][data-test-id="save-template-confirm"], button:contains("Save"):not(:contains("Save template"))')?.click();

// (6) 검증 — 토스트 "Template saved/updated" 노출
await wait(2000);
const toast = /template has been (saved|updated)|Template (saved|updated)|템플릿이 저장되었습니다/i.test(document.body.innerText);
if (!toast) throw new Error('Save/Update 실패 — DOM selector 확인 필요');
```

### 8.3 템플릿명 rev 규칙

| 상황 | 템플릿명 |
|------|---------|
| AI Search direct one-off 저장 | `[포지션]{회사명}, {포지션명}` (예: `[포지션]뤼튼테크놀로지스, AX PM`) |
| legacy bulk 내부 저장(명시 승인 시만) | `{회사명}, {포지션명}_revN` |
| 기존 불량 템플릿 정정 | 같은 이름 검색 -> exact match 로드 -> Update current |
| 같은 회사·포지션 중복 우려 | direct one-off는 같은 이름 재저장 전 기존 템플릿 검색, bulk는 rev 숫자 +1 |

⚠️ `Update current`는 기존 템플릿 정체성이 화면에 확실히 보이는 정정 모드에서만 허용한다. 그 외에는 사장님 기존 템플릿 덮어쓰기 위험 때문에 금지.

---

## 9. Supabase jd_sets 동기화 (옵션 — Phase 2)

본 SKILL 의 1차는 LinkedIn 폼 입력 + 템플릿 저장까지. Supabase `jd_sets.channels.linkedin_inmail` 동기화는 옵션:

```typescript
// jd_sets UPSERT (company_id, position_title) UNIQUE
await supabase.from('jd_sets').upsert({
  company_id,
  position_title,
  jd_text,                                  // §6.2 본문 그대로
  channels: {
    linkedin_inmail: {
      body: BODY_TEXT,
      char_count: [...BODY_TEXT].length,
      template_name: TEMPLATE_NAME,
      saved_at: new Date().toISOString(),
    },
  },
  channels_generated_at: new Date().toISOString(),
  created_by: 'sangmokang@valueconnect.kr',
}, { onConflict: 'company_id,position_title' });
```

⚠️ 1차는 마이그레이션 `20260523000000_jd_sets_and_companies.sql` 미적용 → DB 동기화는 spec 단계. 본 SKILL 흐름은 DB 없이도 100% 동작.

---

## 10. 한 턴 완료 후 보고 형식

사장님께 디스코드 `OPS_CANDIDATES` + Claude Code 응답으로:

```
🟢 LinkedIn JD Set 등록 완료 — {회사} / {포지션}

후보자: {이름} ({현_회사} {현_업무})
프로필: {LinkedIn RPS profile URL}
본문 길이: {N}자 / 1,899자 hard cap
템플릿: "[포지션]{회사명}, {포지션명}" — Anyone in my organization

저장 완료 — Send 보류 (사장님 미리보기 + 발송 게이트)
다음 단계: 미리보기 확인 → 사장님이 직접 [Send] click
```

---

## 11. 오류 처리 (즉시 STOP 조건)

| 신호 | 행동 |
|------|------|
| URL `/checkpoint/`, `/captcha`, `/uas/login` 리다이렉트 | `LinkedInBlockedError` STOP + Discord `OPS_INCIDENTS` 알림 |
| 2FA 코드 요청 화면 노출 | 즉시 STOP — 사장님 수동 풀이 (R3) |
| "Free to InMail" 가 "1 InMail" 로 표시 (차감 안내) | 발송 차감 위험 — 사장님께 라이선스 확인 요청 + STOP |
| Send 버튼 비활성화 (수신자 거부) | 발송 자체 불가 — Save template 만 진행 |
| Save template popover 미노출 (3초 wait 후도) | DOM selector 변경 가능성 — selector dump 후 사장님께 보고 |
| 본문 1,899자 초과 | 자동 발송 차단 — JD bullet 자동 축약 1회 시도 후 그래도 초과 시 STOP |
| `Some variable names are not valid` banner | raw `{{...}}` 변수를 direct composer에 붙인 것. 본문을 `안녕하세요.` 시작의 무변수 문안으로 재작성하거나 LinkedIn native variable UI로만 삽입 |
| `Anyone in my organization`라고 주장했지만 screenshot이 `Only me` | false completion. 라디오 DOM inventory를 다시 뜨고 `Only me=false`, `organization=true`를 pre-save screenshot으로 재확인 후 재저장 |
| 사장님이 chrome 만지면 | tab focus event 감지 → 자동화 action 0 (`[[feedback_human_intervention_pause]]`) |

---

## 12. 사람인/잡코리아 SKILL 통합 (R9 cascade)

본 SKILL 단독으로도 동작하지만, 사람인/잡코리아 SKILL 의 R9 (jd_sets cache) 와 연결되면 효율 ↑:

```
사장님: "사람인 한 턴 — 뤼튼 AX PM" + "LinkedIn 채널도 같이"
   ↓
saramin-talent-sourcing SKILL §R9
   ↓
jd_sets SELECT WHERE company=뤼튼 AND position="AX PM"
   ├─ hit  → channels.linkedin_inmail.body 재사용
   └─ miss → linkedin-rps-jd-set-builder SKILL 호출 → 본문 생성 → jd_sets UPSERT
```

핵심: **본문 1번 생성 = 4채널 재사용** (jd-set-builder design spec §7.5 — 4채널 1턴 JSON 출력).

---

## 13. 참고 자산

| 항목 | 위치 |
|------|------|
| 디자인 스펙 | `docs/superpowers/specs/2026-05-22-jd-set-builder-design.md` |
| 사람인 SKILL | `~/.claude/skills/saramin-talent-sourcing/SKILL.md` |
| 잡코리아 SKILL | `~/.claude/skills/jobkorea-talent-sourcing/SKILL.md` |
| Talent search 메타 | `~/.claude/skills/talent-search/SKILL.md` |
| 디스코드 알림 헬퍼 | `tools/ai-search-shared/src/discord-notify.ts` |
| LinkedIn 워커 (기존) | `tools/linkedin-sourcing/` |
| 칸반 보드 | `/kanban?board=FY26_Candidates` |

---

## 14. 변경 이력

- 2026-05-23 — SKILL 신규 작성. 디자인 spec 의 LinkedIn 1채널을 SKILL 로 실현. R0~R14 절대 규칙 14종 + 7 Phase 흐름 + 당시 1,900자 4단 본문 구성 명시. 발송 금지 + Save as new 템플릿 게이트로 사장님 수동 검토 100% 유지.
- 2026-05-25 — position-batch orchestrator 통합 보강. **R9 양식 변경** (`[회사명] 포지션명` → `회사명, 포지션명`, RPS 한정 — 이메일 subject 와 분리). **R12 강화** (디폴트 유지 → 라디오 명시 클릭 + selected 검증). **R16 신규** (position-batch orchestrator 통합 명문화). **§16.3 batch size 10건 → 25건** (사장님 명시 86건 = 25+25+36 3회차). **§16.4 placeholder** = talent search 임의 프로필 명시 (직접 composer URL 진입 금지). 관련 spec: `docs/superpowers/specs/2026-05-25-position-batch-orchestrator-design.md` §5[4] / §16 R15~R17.
- 2026-06-23 — Codebox/ZUZU live run Golden Sample 반영. direct composer hard cap 1,899자, raw `{{...}}` 변수 금지, owner Chrome 공유 점유권, DOM inventory-first, `[포지션]회사명, 포지션명` subject/template name, `Only me=false` + `Anyone in my organization=true` 라디오 증거, pre/post-save screenshot, Claude adversarial false-completion remediation을 R9/R22/§1A/§5/§8에 추가.
- 2026-06-23 — AI Search process embedding 반영. R26 추가: 신규/현재 포지션 AI Search 완료 보고에 `LinkedIn/RPS JD 템플릿` 레인을 기본 포함하고, 로컬 패키지/브라우저 저장/차단 상태를 분리 보고.
- 2026-07-02 — 모델솔루션 인사담당 라이브 저장(raw CDP 단일탭) 실측 4건: ① composer 하단 `Save as new template` 버튼이 뷰포트(≈1160px) 아래면 좌표 클릭이 헛침 — **클릭 전 `scrollIntoView({block:'center'})` 후 rect 재계산 필수**. ② Save popover는 `[role="dialog"]`가 아니라 **일반 div** — `innerText`에 'Save message template' 포함 & 길이<600인 최소 컨테이너로 탐지. ③ 조직공유 라디오는 input 직접 click이 안 먹으면 `closest('label')` click, 검증은 `input.checked`. ④ 성공 토스트 실측 문구 = `"<템플릿명> template has been saved."`(좌하단). 기존 AI Touch-up 영어 auto-draft가 editor에 남은 케이스 → R1대로 selectAll+delete 후 줄단위 insertText 교체(한국어 1,148자 무손실 주입 검증).
- 2026-07-02(2차, Update current 라이브) 실측 3건: ① **24시간 재접촉 잠금 프로필("cannot be contacted more than once within 24 hours" 배너)에서는 composer 전체가 잠겨 `Save template` 버튼도 disabled** — 본문 편집은 되지만 저장 불가이니, 배너 감지 즉시 다른(미접촉) 프로필 composer로 갈아탄다. ② 템플릿 로드 시 AI Touch-up이 "Touching up the message using AI…"로 composer를 점유 — [Got it] 닫고 busy 텍스트 사라질 때까지 대기 후 진행("Touch up failed…English" 에러는 무시, R1). ③ **저장 후검증 절차 확립**: 본문을 임시 텍스트로 바꾼 뒤 같은 템플릿을 재로드 → `Replace content?` 모달 [Ok] → 재로드된 본문에 새 문구가 있으면 서버 반영 증명(토스트를 놓쳤을 때의 확정 검증법).

---

## 16. ClickUp → LinkedIn Templates 일괄 등록 (Bulk Phase) — 2026-05-23 추가

> 사장님 명시 (2026-05-23) — "발송하는 거 아니면 입력하는데 대신 너무 빨리해서 LinkedIn 보안에 걸리지 않도록 하라". 본 §은 클릭업 FY26ClientsPosition active 분류 86건 → LinkedIn Templates 일괄 등록 흐름. **발송 금지 (R0) 유지** — 템플릿 저장만.

### 16.1 사전 조건 (BLOCKING)

다음 조건이 모두 충족되어야 본 흐름 진입:
1. **사장님 chrome 점유 해제** — LinkedIn composer 닫기 + 사람인/잡코리아 모달 닫기 (`tabs_context_mcp` 로 확인)
2. **첫 라이브 1건 검증 통과** — §3~§8 흐름이 실제 LinkedIn DOM 과 일치 확인 (selector 깨짐 0)
3. **사장님 명시 진입 신호** — "지금 일괄 진행 ㄱㄱ" 또는 "bulk 진행" 명시

위 3개 중 하나라도 미충족 시 STOP + 사장님 보고.

### 16.2 입력 파일

`.omc/linkedin-bulk-active.jsonl` — Phase 0b 에서 생성. 86건 active 분류 포지션.

각 줄 스키마:
```json
{"company":"뤼튼테크놀로지스","position":"[AX CIC] AX Project Manager","status":"po/pm/기획","clickup_id":"86ew25gf6","url":"https://...","priority":"P0"}
```

우선순위 처리 순서: P0 → P1 → P2 (회사명 가나다순)

### 16.3 Bulk Rate Limit 정책 (사장님 명시 — LinkedIn 보안 회피)

| 항목 | 값 | 근거 |
|------|----|------|
| **1포지션당 최소 sleep** | 60초 | 사장님 "너무 빨리하지 마라" 명시. 사람이 손으로 본문 작성 + 검토하는 속도 시뮬레이션 |
| **임의 jitter** | 추가 ±15초 (45~75초 범위) | 머신 패턴 회피 |
| **batch size (회차)** | **25건** | 사장님 명시 (2026-05-25) — 86건 = 25+25+36 3회차 분할 |
| **회차간 휴식** | **5분** | 25건 = 약 25~30분 + 5분 = 30~35분/회차 |
| **총 86건 예상 시간** | **약 75~90분 (1시간 15분~1시간 30분)** | 3회차 × 30~35분 (회차간 휴식 포함). spec 의 [4] RPS Save 단계 70분 추정과 일치 |
| **세션 최대 진행 시간** | 90분 | 90분 초과 시 강제 30분 휴식 |
| **하루 최대 등록** | 30건 | 86건 = 3일 분산 권고 |
| **자동 STOP 신호** | `/checkpoint/`, `/captcha`, 2FA, "unusual activity" | R5 즉시 STOP, 디스코드 `OPS_INCIDENTS` |

### 16.4 placeholder 프로필 전략

LinkedIn RPS 의 "Save template" 흐름은 항상 **특정 후보자 profile 페이지의 composer** 안에서만 동작. Bulk 등록 시:

- **placeholder profile = talent search 결과 화면에서 임의 프로필 클릭 → drawer → "Message" 버튼** (사장님 명시 2026-05-25)
- 직접 composer URL 진입 **금지** (봇 감지 회피)
- 회차(25건)당 1개 placeholder profile 선택 — 25건 모두 같은 composer 안에서 처리 후 close
- 다음 회차 시작 시 **다른 임의 프로필** 선택 (3회차 = 3명 placeholder 권장 — 머신 패턴 추가 회피)
- **메시지 발송 0** (R0) — composer 는 본문 입력 후 항상 Save template → Cancel/X 닫기
- 실제 발송 시점에는 사장님이 **각 후보자별 적합 profile 선택 → 저장된 템플릿 선택 → Send** (수동)

⚠️ **검증**: bulk 1턴 종료 후 placeholder profile 의 "Messages" 탭에 새 message 잔재 0인지 확인. `Messages (1)` 카운트가 시작 시점과 동일해야 함.

### 16.5 Bulk 실행 흐름 (의사 코드)

```typescript
// 0. 사전 점검
const tabs = await tabs_context_mcp();
const linkedinTab = tabs.find(t => t.url.includes('linkedin.com/talent/hire'));
if (!linkedinTab) throw new Error('LinkedIn RPS profile 탭 없음 — 사장님 placeholder profile 열어주세요');

const tasks = readJsonl('.omc/linkedin-bulk-active.jsonl');
tasks.sort((a, b) => a.priority.localeCompare(b.priority) || a.company.localeCompare(b.company));

let processed = 0, batchCount = 0;
const startTime = Date.now();

for (const task of tasks) {
  // (1) 90분 강제 휴식
  if (Date.now() - startTime > 90 * 60 * 1000) {
    discord.alert(`90분 도달 — 30분 휴식. ${processed}/${tasks.length} 완료`);
    await sleep(30 * 60 * 1000);
    startTime = Date.now();
  }

  // (2) 봇 검출 신호 모니터링 (매 5건마다)
  if (processed % 5 === 0) {
    const url = await currentUrl(linkedinTab.tabId);
    if (/checkpoint|captcha|uas\/login|unusual/i.test(url)) {
      discord.alert('🛑 LinkedIn 봇 검출 신호 감지 — 즉시 STOP');
      throw new BotDetectedError(url);
    }
  }

  // (3) clickup task description 가져오기 (회사 brief + JD 본문)
  const jdTask = await clickup_get_task(task.clickup_id);
  const jdText = jdTask.description || jdTask.text_content || '';

  // (4) 회사 brief 자동 추출 (JD 본문에서)
  //   - "회사 소개" / "회사 정보" / "[회사명]" 섹션 또는
  //   - 매출/투자/MAU/인원 키워드 라인 추출
  const companyBrief = extractCompanyBrief(jdText, task.company);

  // (5) 본문 4단 조합 + 1,899자 검증
  const body = composeBody({
    candidate_name: '___',  // placeholder — 실제 발송 때 사장님이 수동 치환
    candidate_headline: '___',
    company: task.company,
    position: task.position,
    company_brief: companyBrief,
    jd_text: jdText,
  });
  if ([...body].length > 1899) {
    body = autoShrinkJD(body, 1899);  // JD bullet 줄이기 1회 시도
  }
  if ([...body].length > 1899) {
    log.warn(`${task.company} / ${task.position} — 1,899자 초과 (${[...body].length}자) — 건너뜀`);
    continue;
  }

  // (6) Subject + Body 입력 + Save as new
  await openCompose(linkedinTab.tabId);
  await dismissTouchUp(linkedinTab.tabId);                     // §4
  await setSubject(linkedinTab.tabId, `[포지션]${task.company}, ${task.position}`);  // §5 (R9 — AI Search direct RPS subject)
  await setBody(linkedinTab.tabId, body);                       // §6.4
  await saveAsNewTemplate(linkedinTab.tabId, `${task.company}, ${task.position}_rev1`);  // §8 (R12 — Anyone in my organization 라디오 명시 클릭 검증)

  // (7) composer 닫기 (Send 누르지 않음 — R0)
  await closeCompose(linkedinTab.tabId);                        // X 또는 Cancel

  // (8) Discord 진행 보고 (회차당 25건)
  processed++;
  if (processed % 25 === 0 && processed < tasks.length) {
    discord.report(`📦 ${processed}/${tasks.length} 완료 — 회차 ${Math.floor(processed/25)} 종료. 5분 휴식 시작.`);
    await sleep(5 * 60 * 1000);  // 회차간 휴식 (사장님 명시 2026-05-25)
    batchCount++;
    // 다음 회차 시작 시 다른 placeholder profile 로 재진입 권장
    await pickNewPlaceholderProfile(linkedinTab.tabId);
  }

  // (9) 다음 포지션 sleep (60s + jitter ±15s)
  const sleepMs = (60 + (Math.random() - 0.5) * 30) * 1000;
  await sleep(sleepMs);
}

discord.report(`✅ 전체 86건 완료 — 총 ${(Date.now() - startTime) / 60000}분 소요`);
```

### 16.6 회사 brief 자동 추출 로직 (`extractCompanyBrief`)

JD 본문(`pipeline_jds.jd_text` 또는 ClickUp task description)에서 회사 brief 추출:

```typescript
function extractCompanyBrief(jdText: string, companyName: string): string {
  // (a) "회사 소개" / "회사 정보" / "About us" 섹션 우선
  const sections = jdText.split(/\n#{1,3}\s+/);
  const aboutSection = sections.find(s =>
    /회사\s*소개|회사\s*정보|About\s*(us|the\s*company)|기업\s*소개/i.test(s)
  );
  if (aboutSection) return aboutSection.slice(0, 400).trim();

  // (b) 매출/투자/MAU/인원 키워드 라인 추출
  const lines = jdText.split('\n');
  const briefLines = lines.filter(l =>
    /매출|투자|MAU|인원|직원|founded|series\s*[A-Z]|funding|raised|million|억\s*원/i.test(l)
  );
  if (briefLines.length > 0) return briefLines.slice(0, 5).join('\n');

  // (c) fallback — 첫 200자 (보통 JD 시작이 회사 소개)
  return jdText.slice(0, 400).trim();
}

function autoShrinkJD(body: string, maxChars: number): string {
  // 자격 요건 / 우대사항 bullet 1개씩 줄이며 maxChars 이하 도달까지 반복
  // 단 주요 업무 + 회사 brief + 인사 + 절차는 절대 줄이지 않음
  ...
}
```

⚠️ R6 (회사 리서치 사장님 검토) — bulk 시점에서는 자동 추출 본문이 1차. 사장님이 발송 시점에 각 템플릿 검토 후 수정. 절대로 본 SKILL 이 직접 발송하지 않음.

### 16.7 진행 보고 형식 (Discord OPS_CANDIDATES)

매 batch (10건) 완료 시:

```
📦 LinkedIn Templates Bulk 등록 — Batch {N}/9 완료

진행: {processed}/86 ({percent}%)
경과: {minutes}분
batch 평균 시간: {avg_per_batch}분
다음 batch 시작: 5분 후

이번 batch 등록한 템플릿:
1. [뤼튼테크놀로지스] [AX CIC] AX Project Manager_rev1
2. [뤼튼테크놀로지스] [AX CIC] Backend Engineer_rev1
...
10. [뤼튼테크놀로지스] AI Account Executive_rev1

봇 검출 신호: 없음 (clean)
잔여 sleep budget: {remaining_minutes}분
```

전체 완료 시:

```
✅ LinkedIn Templates Bulk 등록 완료 — 86/86

회사별 등록:
- 뤼튼테크놀로지스: 28건
- 코드잇: 17건
- 스푼랩스: 14건
- 역전에프앤씨: 7건
- ...

총 소요: {total_minutes}분 (예상 150분 vs 실제 {actual}분)
봇 검출 인시던트: 0건
사장님 검토 대기: 86건 — LinkedIn Templates 페이지에서 확인 가능
다음 단계: 후보자별 발송은 사장님 수동 (R0 유지)
```

### 16.8 중단 후 재시작 (resume)

bulk 도중 사장님 chrome 개입(R4) 또는 봇 검출(R5) 또는 90분 휴식 등으로 중단 시:

- `.omc/linkedin-bulk-progress.json` 에 `{ processed: N, last_clickup_id: '...', last_at: '...' }` 자동 저장
- 재시작 시 `processed` 이후부터 진행 (중복 등록 방지)
- 같은 회사·포지션 재등록 시 LinkedIn Templates 의 기존 rev 확인 후 `_revN+1` 로 변경

### 16.9 사후 검증 (Discord 알림 후)

bulk 완료 후 사장님이 수동으로:
1. LinkedIn Templates 페이지 진입 — 86건 신규 템플릿 노출 확인
2. 임의 5건 샘플 — 제목/본문 글자수/구조 검증
3. placeholder profile Messages 탭 — 잔재 message 0 확인 (R0 준수)

검증 통과 후 사장님이 각 후보자에게 매칭되는 템플릿 선택 → 수동 발송 시작.

---

## 15. Acceptance Criteria (1차 완료 정의)

다음이 모두 참이면 본 SKILL 1차 완료:

- [ ] SKILL 트리거 키워드 6종 노출 → 사장님 1줄 명령으로 활성화
- [ ] LinkedIn RPS profile URL 진입 + Compose Message 패널 노출 검증
- [ ] AI Touch up auto-draft 패널 [Got it] 자동 닫기
- [ ] Subject `[포지션]회사명, 포지션명` 입력 (React 호환 setter 우회)
- [ ] 본문 4단 1,899자 이내 + execCommand insertText 안전 입력
- [ ] Preview click + screenshot 캡처 + Discord OPS_CANDIDATES embed 송부
- [ ] Save template → 신규는 Save as new, 정정은 exact 기존 템플릿 Update current → 템플릿명 `[포지션]{회사명}, {포지션명}` + `Only me=false` / `Anyone in my organization=true` DOM 확인 + pre/post-save/update screenshot
- [ ] Send 버튼은 절대 자동 click 하지 않음 (R0)
- [ ] 첫 라이브 검증 — 뤼튼 AX PM 박상아 매니저(또는 임의 1명) 1건 정상 저장 (사장님 라이브 확인)

### 2차 Acceptance (Bulk Phase §16)

- [ ] `.omc/linkedin-bulk-active.jsonl` 86건 작성 완료
- [ ] §16 Rate Limit 정책 (60s + jitter / 10건 5분 / 90분 30분 / 일 30건) SKILL 명문화
- [ ] placeholder profile 1개 선택 후 86건 모두 같은 composer 에서 진행
- [ ] 봇 검출 모니터링 5건마다 + R5 즉시 STOP
- [ ] `.omc/linkedin-bulk-progress.json` resume 메커니즘 동작
- [ ] 전체 완료 후 LinkedIn Templates 페이지 86건 노출 확인
- [ ] placeholder profile Messages 잔재 0 (R0 준수)

---

## §S. 다중 키워드 검색 시나리오 플래닝 엔진 — LinkedIn RPS 후보자 서치 (2026-06-18 사장님 명시)

> "링크드인 RPS는 써치 안해?" — 사장님 명시. JD 템플릿 저장 외에 **LinkedIn Recruiter 검색 포털에서 다중 키워드 시나리오로 후보자를 발굴**하는 §S를 추가.

### §S-0. 이 채널(LinkedIn RPS)의 적용 컨텍스트

- **LinkedIn Recruiter(RPS) 검색 화면**에서 매 시나리오를 실행한다. (JD 템플릿 저장과 별개 흐름)
- **봇 탐지 민감도**: 사람인·잡코리아보다 훨씬 높음 → 딜레이 20~60초 (랜덤)
- **캡차·차단 감지 즉시 STOP** (R5) — 재시도 절대 금지, 디스코드 `OPS_INCIDENTS` 알림
- **R3 준수**: 사장님 Chrome (:9222) 세션만 사용. 별도 로그인 자동화 금지
- **R4 준수**: 사장님이 Chrome 개입 시 즉시 자동화 정지
- 시나리오 수를 사람인·잡코리아보다 줄여(8개 내외) 봇 탐지 위험 최소화

### §S-1. 결과 수 즉시 판단 의사결정 트리 (LinkedIn RPS 기준)

```
키워드 입력 → 결과 수 읽기 (상단 "X results")
      │
      ├─ 0~4명  → [즉시 포기] 다음 시나리오 (30초 대기 후)
      │
      ├─ 5~60명 → [GOLD] 전수 처리
      │             ① 프로필 URL 수집
      │             ② 이직잦음·프리랜서 제외
      │             ③ dedup 후 통합 pool에 추가
      │             ④ InMail 템플릿 저장 대상으로 등록
      │
      ├─ 61~200명 → [부분 처리] 상위 20명 (추천순 1페이지)만
      │              → 처리 완료 후 20~40초 대기 → 다음 시나리오
      │
      └─ 200명+  → [AND 재시도] 조건 추가 후 재검색
                    AND 추가 후에도 200+ → 즉시 포기
```

> LinkedIn RPS는 사람인·잡코리아보다 GOLD 임계값이 낮음(5~60명). 60명 초과 시 LinkedIn 알고리즘 정렬 신뢰도가 떨어짐.

### §S-2. Finance/Data 포지션 LinkedIn 키워드 시나리오 (8개 기준)

| 시나리오 | 검색어 | 필터 | 예상 결과 | 딜레이 |
|---------|-------|------|---------|-------|
| L1 | `FP&A` | Location: South Korea | 10~60명 | 20~40초 |
| L2 | `Finance Data Analyst` | Location: Seoul | 5~30명 | 20~40초 |
| L3 | `SQL Finance` | South Korea | 10~40명 | 30~50초 |
| L4 | `dbt Finance` | South Korea | 3~15명 | 30~60초 |
| L5 | `FinOps SaaS` | South Korea | 3~20명 | 30~60초 |
| L6 | `IR Factbook Finance` | South Korea | 3~15명 | 20~40초 |
| L7 | `Financial Planning Data` | South Korea | 10~50명 | 20~40초 |
| L8 | `KPI Metrics Finance` | South Korea | 10~60명 | 20~40초 |

> L4·L5·L6 는 결과 0~4명이면 즉시 포기(딜레이 30초 후 다음). 소수정예 발굴 우선.

### §S-3. 시나리오 실행 흐름

```javascript
async function runLinkedInScenarioEngine(jd, page) {
  const scenarios = buildLinkedInScenarios(jd); // L1~L8 또는 JD 기반 생성
  const pool = new Map(); // profile_url → candidate

  for (const s of scenarios) {
    // 1. 캡차·차단 상태 먼저 점검 (R5)
    if (await isLinkedInBlocked(page)) {
      await notifyDiscord('OPS_INCIDENTS', `LinkedIn 캡차 감지 — 시나리오 중단`);
      break; // 재시도 금지
    }

    // 2. 검색어 입력 (clipboard paste, R10)
    await linkedInSearch(page, s.keyword, { location: s.location });

    // 3. 결과 수 즉시 확인
    const count = await getLinkedInResultCount(page);

    // 4. 즉시 판단
    if (count < 5) {
      await randomDelay(25, 40); // LinkedIn 봇 탐지 위해 대기
      continue;
    }

    if (count > 200) {
      // 조건 추가 후 재시도 1회만
      await addLinkedInFilter(page, s.narrowFallback || 'South Korea');
      const newCount = await getLinkedInResultCount(page);
      if (newCount < 5 || newCount > 200) {
        await randomDelay(25, 40);
        continue;
      }
    }

    // 5. GOLD 처리
    const limit = count <= 60 ? count : 20;
    const candidates = await collectLinkedInCandidates(page, limit);
    for (const c of candidates) {
      if (pool.has(c.profile_url)) continue;
      if (hasFrequentJobChange(c.careerPath) || isFreelancer(c)) continue;
      pool.set(c.profile_url, { ...c, scenario: s.id });
    }

    // 6. LinkedIn 봇 회피 딜레이 (20~60초 랜덤)
    await randomDelay(20, 60);
  }

  return Array.from(pool.values());
}

function hasFrequentJobChange(careerPath) {
  if (!careerPath || careerPath.length === 0) return false;
  const shortStints = careerPath.filter(j => parseMonths(j.period) < 12 && isWithin5Years(j.endDate));
  return shortStints.length >= 2;
}

function isFreelancer(candidate) {
  const markers = ['freelance', 'freelancer', '프리랜서', '개인사업자', 'independent'];
  const text = (candidate.headline + ' ' + candidate.currentTitle).toLowerCase();
  return markers.some(m => text.includes(m));
}
```

### §S-4. JD → LinkedIn 시나리오 생성 규칙

1. **P1 정밀**: JD 핵심 도구 키워드(SQL·dbt·Airflow·FinOps·IR) 하나씩 + "Finance" OR "South Korea"
2. **P2 중간**: 직무명 영문 (Finance Data Analyst, FP&A) 단독
3. **P3 광범위**: 직무 상위 카테고리 (Financial Planning, Business Intelligence)

LinkedIn은 사람인·잡코리아보다 시나리오 수를 **8개 이내**로 제한한다. 봇 탐지 위험 > 추가 수집 이익.

### §S-5. 완료 보고 형식

```
🟢 LinkedIn RPS 시나리오 서치 완료 — {포지션명}

총 시나리오: {N}개
  GOLD 수집: {M}개
  즉시 포기(결과 0~4명): {K}개
  봇 탐지 STOP: 0건 (or N건)

수집 결과:
  원시 후보: {X}명
  dedup 후: {Y}명
  이직잦음/프리랜서 제외: {Z}명
  최종 후보: {W}명 → InMail 템플릿 저장 대상

다음 단계: 위 {W}명에 대해 §1~§15 InMail 템플릿 저장 진행
```

### §S-6. §S와 기존 SKILL(§1~§15 템플릿 저장) 연계

```
[LinkedIn RPS 전체 흐름]
  §S  → 후보자 발굴 (다중 키워드 서치)
    ↓
  §1~§15 → 각 후보자별 InMail 템플릿 저장 (JD Set Builder)
    ↓
  사장님 수동 발송 (R0 — Send 자동 클릭 절대 금지)
```

§S에서 수집한 후보 목록을 §16 Bulk 흐름의 입력으로 그대로 사용한다.
