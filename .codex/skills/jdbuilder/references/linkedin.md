# LinkedIn InMail 템플릿 저장

(구 `linkedin-rps-jd-set-builder`(955줄) 흡수·압축. R번호는 원본 그대로 유지 — 참조 추적용)

## 절대 규칙 (원본 R0~R26 요지)

| # | 규칙 |
|---|------|
| R0 | Send 버튼 절대 자동 click 금지 — Save template까지만. |
| R1 | AI Touch up auto-draft 패널은 [Got it] 또는 X로 닫는다(영문 한정 오류는 무시). |
| R2 | 본문 총 **1,899자 hard cap**(플랫폼 실측 상한, 변경 불가) — 1,800~1,899자 목표(R5 글자수 최대화). |
| R3 | 자격증명·세션은 사장님 chrome(:9222) 세션 의존 — 별도 로그인 자동화 금지. |
| R4 | 사람 개입(chrome 조작) 감지 시 자동화 즉시 정지. |
| R5 | 봇 검출(캡차/차단/2FA) 즉시 STOP — 재시도 금지, Discord `OPS_INCIDENTS` 알림. |
| R7 | 회사 매출/투자/인원 수치는 출처 있는 것만(company-research.md 5요소). |
| R8 | JD 원본 훼손 금지 — 어투 조정만, 책임범위·자격요건은 원문 그대로. |
| R9 | Subject/템플릿명 = `[포지션]회사명, 포지션명`. |
| R10 | 한국어 textarea 입력은 clipboard + execCommand 패턴(자모분리 방지). |
| R11 | 신규 생성 = "Save as new", 정정 = 기존 템플릿 검색 후 "Update current". |
| R12 | 템플릿 visible = "Anyone in my organization" 라디오 명시 클릭 + 양방향 검증(Only me=false 확인). |
| R20 | 도입부 회사 브리핑 — company-research.md 5필수요소 반영. |
| R21 | 마무리 CTA 1줄 필수 — SOT-10 §1④ 문구(valuehire.cc/resume) + 서명. |
| R25 | raw `{{...}}` 변수/HTML comment 금지 — invalid-variable banner 유발. |

## 진입 + 개인화 데이터 추출 (R2 개인화 필수)
1. 프로필 URL 진입(`.../talent/hire/{projectId}/discover/recruiterSearch/profile/{candidateId}/messages?...rightRail=composer`), 5초 대기(lazy load).
2. Compose Message 패널 미노출이면 InMail 아이콘 click.
3. 사이드바에서 개인화 재료 추출: `name, headline, currentCo, currentRole, school, location` (selector는 LinkedIn 분기 변경 잦음 — 실패 시 텍스트 dump 후 LLM 1턴 추출 폴백).

## AI Touch up 닫기
```js
document.querySelector('button[aria-label*="Got it"]')?.click();
// 실패 시 X 닫기. [View settings]는 절대 click 금지(계정 설정 영향).
```

## Subject 입력
```js
const subject = document.querySelector('input[name="subject"], input[placeholder*="Subject"]');
const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
setter.call(subject, `[포지션]${COMPANY_SHORT}, ${POSITION_TITLE}`);
subject.dispatchEvent(new Event('input',{bubbles:true}));
```

## 본문 7단 구성 (1,899자 이내, R5 글자수 최대화 — 1,800~1,899 목표)

| 단 | 글자수 | 내용 |
|---|---|---|
| ①인사 | 120~220자 | `안녕하세요! Tech Searchfirm 밸류커넥트(valueconnect.kr)의 강상모입니다.` + **후보자 이름/헤드라인 반영 개인화 hook**(범용 인사말 금지) |
| ②회사/서비스 | 250~400자 | company-research.md 5요소 중 확인된 것만 |
| ③일하는 방식(있으면) | 200~350자 | 5원칙 등 공개 시 bullet로 균형 분할, 없으면 생략 |
| ④포지션 핵심 | 450~650자 | JD 주요업무 4~6 bullet, 원문 훼손 금지(R8) |
| ⑤왜 검토할 만한가 | 250~400자 | 2~5 bullet |
| ⑥자격/우대 | 220~350자 | JD 원문 그대로, 창작 금지 |
| ⑦클로징+CTA(R21) | 150~300자 | 강상모 드림 + SOT-10 §1④ CTA(valuehire.cc/resume) |

입력: `editor.focus()` → `execCommand('selectAll')`+`delete`(잔재 제거) → `execCommand('insertText', false, BODY_TEXT)` → 길이 검증. 첫 문단만 들어가면 줄단위 `insertLineBreak`+`insertText` 반복.

추가 검수: 한 줄 180자 초과, raw `**About`, `•`, 원본 JD 문단 덤프가 있으면 Save 금지. subject/body/counter 검증 뒤 Preview 또는 DOM 값으로 실제 줄바꿈을 확인한다.

## Save as new / Update current (R11·R12)
```js
const TEMPLATE_NAME = `[포지션]${COMPANY_NAME}, ${POSITION_TITLE}`;
// 신규: "Save as new" 탭. 정정: 같은 이름 검색 → exact match 로드 → "Update current"(없으면 중단, 중복생성 금지)
// 저장 팝오버 안 "Anyone in my organization" 라디오 — 양방향 확인:
if (!org.checked) org.el.click();
if (onlyMe.checked) throw new Error('Only me 선택 상태 — Save 금지');
// 성공 토스트: "<템플릿명> template has been saved."
```

## 함정 (실측)
- 저장 버튼이 뷰포트 밖이면 클릭 전 `scrollIntoView({block:'center'})` 필수.
- Save popover는 `[role="dialog"]`가 아니라 일반 `div` — innerText로 탐지.
- 24시간 재접촉 잠금 프로필은 composer 전체가 잠겨 Save도 disabled — 다른 프로필로 갈아탄다.
- raw `{{firstName}}` 변수는 direct composer에서 invalid-variable 배너 유발 — 실제 이름을 문자열로 삽입한다(R2 개인화, 변수 치환 아님).

---

## 부록 — LinkedIn RPS 후보자 검색(§S, JD 등록과 무관, 지식 보존용)

이 부록은 **jd-builder 범위 밖**이다(후보자 검색은 별도 관심사). 향후 "LinkedIn 후보자 검색" 전용 스킬이 필요하면 여기서 이관한다. 원본 요지: 다중 키워드 시나리오(8개 이내, 결과 5~60명 GOLD 임계값) → dedup → InMail 템플릿 저장 대상 pool 생성. 봇탐지 딜레이 20~60초, 캡차 즉시 STOP. 상세 시나리오 표·의사코드는 git 이력의 `linkedin-rps-jd-set-builder` 스킬(삭제 전 버전, `git log -- ~/.claude` 해당 없음 — 로컬 파일이라 백업 필요 시 `docs/sot/25` 변경이력 참고)에 있었다.
