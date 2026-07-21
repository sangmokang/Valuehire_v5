---
name: recruit-post-builder
description: 사장님(밸류커넥트) 채용공고를 사람인 기업회원(/recruit/add) · 잡코리아 서치펌(/Corp/Recruit/Regist) · LinkedIn RPS InMail 템플릿 세 채널에 자동 등록하고, 그 결과 URL을 메일로 1회 발송. 인재 검색·제안 발송용 saramin-talent-sourcing / jobkorea-talent-sourcing SKILL 과 별도 — 이 SKILL 은 "채용공고 등록(Job Posting)" 자체 자동화. position-batch-flow orchestrator 의 새 단계로 호출. 캡차·기업인증·자격증명 만료·사장님 chrome 점유 같은 사람 개입 게이트 모두 R-규칙으로 명문화. 트리거 키워드 — "채용공고 등록", "포지션 등록 자동", "recruit post", "3채널 등록", "JD Set 게시", "사람인 잡코리아 RPS 자동 등록".
---

# Recruit Post Builder — 3채널 채용공고 등록 자동화

> 2026-05-29 사장님 명시 ("이 과정 매우 중요함. 프로세스 제대로 정리해서 프로젝트 중요도 최상위로 올려줘") — 뤼튼 Global Growth Marketer (북미) 라이브 검증 후 영구 명문화. 기존 `saramin-talent-sourcing` / `jobkorea-talent-sourcing` SKILL 은 인재DB **검색 + 제안 발송** 흐름, 본 SKILL 은 사장님 회사의 **채용공고 게시 (Job Posting)** 흐름으로 별도 정립.

---

## 0. 절대 규칙 (사장님 명시 — 절대 위반 금지)

| # | 규칙 | 근거 |
|---|------|------|
| **R0** | **자동 게시 절대 금지** — 사람인 `사전 확인 서비스` / 잡코리아 `등록완료` / LinkedIn `Send` 모두 사장님 수동 클릭. 자동화는 **임시저장 / Save as new** 까지만. | 채용공고 게시 = 비용 차감 + 후보자 노출 = 되돌릴 수 없음 |
| **R1** | **자격증명 SKILL 평문 금지** — `~/.secrets/{saramin,jobkorea}.env` 격리(chmod 600). LinkedIn 은 사장님 chrome :9222 세션 의존. | 사람인은 2026-05-29 시점 `.env` 파일 부재 — 메모리 [[reference_saramin_env_missing]] 와 일치. SKILL 메모리에 ID/PW 명문 금지 |
| **R2** | **사장님 chrome :9222 점유 감지 시 즉시 정지** — `tabs_context_mcp` 호출하여 사장님이 사용 중인 ChatGPT·인재검색·이력서 보기 등 탭 발견 시 자동화 보류. | 메모리 [[feedback_chrome_9222_also_owner_active_2026_05_27]] + [[feedback_human_intervention_pause]] |
| **R3** | **캡차/봇 검출 즉시 STOP, 재시도 금지** — "여러 번 실패 기록" 메시지 + 그림문자 캡차 발견 시 계정 잠금 위험으로 즉시 정지. 재시도 = 잠금. | 2026-05-29 14:15 KST 잡코리아 라이브 검증 — [[QA-258]] |
| **R4** | **사람 개입 게이트 명문화** — 캡차 발견 시 사장님께 "현 화면에서 직접 캡차 입력 + 로그인 완료 후 알려주세요" 안내 + 그 탭은 그대로 유지. 사장님 OK 받으면 자동화 이어서 진행. | 사장님 2026-05-29 명시 "로그인시 사람이 개입할 수 있도록 로직 보강" |
| **R5** | **자격증명 60일 회전 경고** — env 파일 mtime 이 60일 경과 시 "PW 회전 권장" 출력. 잡코리아 강제 변경 정책 (90일) 보다 보수적. | [[QA-258]] 추정 원인 — PW 회전 미반영 |
| **R6** | **본문은 `jd-set-sample.json` (또는 동등 spec) 의 channel body 그대로 입력** — 압축·재가공 금지. R8 (saramin-talent-sourcing) 패턴과 동일. | 메모리 [[project_saramin_v2_live_validation_2026_05_23]] |
| **R7** | **모든 한국어는 JS 코드 escape (`\\uXXXX`) 없이 직접 문자 사용** — "뤼튼" → "뛤튼" 자모 분리 사고 방지. | 사람인 SKILL R9 동일 패턴 |
| **R8** | **input 값 설정은 native setter + dispatch 패턴** — `Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(el, val)` + `input`/`change` 이벤트. React state sync 보장. | 사람인 SKILL R10 |
| **R9** | **SmartEditor2 (잡코리아 모집요강) 는 nested iframe 처리** — 외부 `iframe[src*="SmartEditor2"]` 내부에 `#se2_iframe` (실 입력 영역) → 그 iframe 의 body.innerHTML 직접 설정 + 외부 `textarea.se2_input_syntax` 2개 sync. | 2026-05-29 라이브 검증 |
| **R10** | **버튼 click 은 fullClick pattern (9 mouse events)** — JS `.click()` 만으로는 React handler 가 종종 무시. `pointerover/enter/mouseover/enter/pointerdown/mousedown/pointerup/mouseup/click` sequence + Enter key 폴백. | 사람인 SKILL R18 동일 검증 |
| **R11** | **사람인 자동 모달 ("이전 공고 불러오기" / "AI 공고 초안 만들기") 우선 닫기** — 페이지 진입 시 자동 모달 떠 있으면 임시저장 click 이 가려짐. ESC 5번 또는 close 버튼으로 모든 모달 닫기 후 임시저장. | 2026-05-29 라이브 검증 (잘못된 모달 click 으로 AI 초안 모달 추가 발생) |
| **R12** | **임시저장 결과는 list 페이지에서 ID 검증** — 사람인 `https://hiring.saramin.co.kr/recruit?mode=incomplete&type=all&page=1` 미완성 탭 / 잡코리아 `https://www.jobkorea.co.kr/Corp/GiMng/List?KCFlag=4` 임시저장 탭 진입 후 카드 추출 + `rec_idx` (사람인) / KCFlag (잡코리아) ID 확보. | 2026-05-29 검증 — 임시저장 click 시 silent 동작도 있어 list 확인 필수 |
| **R13** | **잡코리아 `/Job/Reg` (기업회원 전용) → 메인 redirect, 서치펌 회원은 `/Corp/Recruit/Regist`** — 사장님 잡코리아 계정 = `searchfirm` 타입. corp 사이트 URL 다름. | [[QA-258]] 발견 |
| **R14** | **잡코리아 채용공고 게시 = 기업인증 (사업자등록증명원 발급번호) 필수** — 임시저장은 인증 없이 가능하나 게시는 차단. 사장님 수동 인증 후 사장님 수동 게시. | 2026-05-29 라이브 발견 |
| **R15** | **`tabs_context_mcp` 로 사장님 활성 탭 보호** — 자동화 진입 직전 + 새 탭 생성 후 항상 호출. 사장님이 ChatGPT/인재검색/이력서 본 탭 발견 시 그 탭 ID 는 가로채지 않음, 새 탭 생성. | 2026-05-29 사장님 인재검색 도중 자동화 중복 발견 |
| **R16** | **mjs/Node 자동화는 worktree 기준 + main repo 미수정** — `tools/recruit-post-builder/` 또는 worktree `scripts/` 에 작성. `main` 브랜치 git push 금지. | 사장님 명시 |
| **R17** | **메일 발송은 sendGmailOAuth + lock 파일 1회 보장** — `src/jd-set/lib/gmailOAuthSender.ts` `sendGmailOAuth` 함수 + `send.lock.json` 패턴 재사용 (각 작업별 lock 파일명 분리). | [[project_jd_set_builder_2026_05_25]] |
| **R18** | **사장님 수동 후속 단계는 메일 본문에 카드 형태로 포함** — 각 채널별 (a) 등록 URL (b) 본문 글자수 (c) 마감일 (d) 미완 필드 (e) 게시 가이드 명시. | 2026-05-29 사장님 명시 메일 spec |
| **R19** | **모든 작업은 QA 이슈 + history.md 연동** — 실패/캡차/모달 noise 발견 시 `docs/engineering/qa/issue-log.md` 에 QA-XXX 등록 + worktree `history.md` entry 추가. | 사장님 명시 "이거 history.md 에 중요한 이슈로 등록해" |
| **R20** | **position-batch-flow orchestrator 와 통합** — `tools/position-batch/orchestrator.mjs` 의 신규 단계 `[5] recruit_post` 로 본 SKILL 호출. 결과는 Supabase `position_batch_steps` 의 `step='recruit_post'` 로 적재 + chrome-guard 체크. | 사장님 명시 "position-batch 통합" |

---

## 1. 환경 준비

```bash
# (a) 자격증명 격리
# 사람인 — 2026-05-29 시점 부재, 사장님 수동 생성 권장:
cat > ~/.secrets/saramin.env <<'EOF'
export SARAMIN_ID="valueconnect"
export SARAMIN_PW="<사장님 직접 입력>"
export SARAMIN_ACCOUNT_TYPE="corp"   # 기업회원 (서치펌 아님 — corp 사이트 `recruit/add` 용)
EOF
chmod 600 ~/.secrets/saramin.env

# 잡코리아 — 이미 존재 (2026-05-22 격리):
ls -la ~/.secrets/jobkorea.env   # -rw------- 760B
source ~/.secrets/jobkorea.env
echo "ID:$JOBKOREA_ID  TYPE:$JOBKOREA_ACCOUNT_TYPE"
# TYPE=searchfirm 이면 잡코리아 서치펌 회원, `Corp/Recruit/Regist` 사용

# (b) Chrome 디버그 모드 (R2 점유 검증 후)
curl -sS http://127.0.0.1:9222/json/list | jq '[.[] | select(.type=="page") | {title, url}]'
# 사장님 활성 탭 발견 시 R2 — 자동화 보류 또는 별도 chrome 인스턴스 (port 9333) 띄우기

# (c) 60일 회전 경고
for f in ~/.secrets/{saramin,jobkorea}.env; do
  if [[ -f "$f" ]]; then
    age=$(( ($(date +%s) - $(stat -f %m "$f")) / 86400 ))
    [[ $age -gt 60 ]] && echo "⚠️  $(basename $f) age=${age}일 — PW 회전 권장 (R5)"
  fi
done

# (d) Gmail OAuth 토큰 확인
ls -la /Users/kangsangmo/Desktop/Valueconnect-Ops/apps/gmail-clickup-sync/config/gmail-token-send.json
```

---

## 2. 트리거 입력

| 패턴 | 입력 예시 | SKILL 행동 |
|------|----------|----------|
| **A. 단일 포지션 (full)** | "뤼튼 Global Growth Marketer (북미) 3채널 등록해줘" | jd-set-sample 합성 → 3채널 자동 진입 |
| **B. position-batch 통합** | orchestrator 가 `step='recruit_post'` 로 본 SKILL 호출 | 입력 포지션 N건 × 3채널 = 3N 임시저장 |
| **C. JD Set Builder cascade** | jd-set-builder 산출물 (`jd-set-sample.json`) 받아서 그대로 입력 | 본문 생성 0, 등록만 |

---

## 3. 3채널 등록 흐름

### 3.1 사람인 (기업회원 `recruit/add`)

```javascript
// 1. tabs_context_mcp → 새 탭 생성 (R15)
// 2. navigate https://hiring.saramin.co.kr/recruit/add
//    → 미인증 시 https://www.saramin.co.kr/zf_user/auth?ut=c&url=... 로 redirect
// 3. 로그인 — input[name="id"] + input[type="password"] + 로그인 button
//    R3 — 캡차 발견 시 즉시 STOP, 사장님 수동
// 4. recruit/add 폼:
//    - input#recruit-title (공고제목, maxLen 60)
//    - input#division-name-0 (모집분야명, maxLen 30)
//    - textarea#task-detail-0 (주요업무, 3000자 한도, R6 본문 그대로 입력)
//    - 그 외 경력/학력/직무/고용형태/급여/근무지 등은 라디오/dropdown
//    - R11: 페이지 진입 시 "이전 공고 불러오기" 자동 모달 떠 있으면 ESC 닫기
// 5. 우측 floating button.SideActionButtons_side-buttons "임시저장" 클릭
//    R10 fullClick pattern
// 6. R12: https://hiring.saramin.co.kr/recruit?mode=incomplete&type=all&page=1
//    미완성 탭 → 카드 a 의 search.rec_idx 추출
// 7. 미완성 → "이어서 등록" 버튼 click → URL = /recruit/continue/{rec_idx}
//    R0 — 사장님 수동 추가 채움 + 사전 확인 서비스 신청
```

### 3.2 잡코리아 (서치펌 `/Corp/Recruit/Regist`)

```javascript
// 1. tabs_context_mcp → 새 탭 (R15)
// 2. navigate https://www.jobkorea.co.kr/Login → 기업회원 탭 → 서치펌 회원
//    input[name="M_ID"] + input[name="M_PWD"] + 로그인
//    R3 — "여러 번 실패 기록" + 캡차 시 즉시 STOP
// 3. R13: /Job/Reg → 메인 redirect. 서치펌은 /Corp/Recruit/Regist 사용
// 4. navigate https://www.jobkorea.co.kr/Corp/Recruit/Regist
// 5. 폼:
//    - input[name="Job_Field_Entity"] (직무명 input, placeholder "최대한 직무명을 포함하여 입력하세요")
//    - input[name="AGI_Entity.Career_Year_Cnt"] (경력 년수)
//    - input[name="AGI_Entity.Pay_Range_Start/End"] (급여)
//    - input[name="AGI_Entity.Apply_Start_Str/Close_Str"] (모집기간, default 90일)
//    - input[name="AGI_Entity.Ofc_Man_Name/Dept_Name/Phone_No1/2/3"] (담당자)
//    - 모집요강 = SmartEditor2 iframe (R9 nested iframe)
// 6. R9: iframe[src*="SmartEditor2"] → #se2_iframe → contentDocument.body.innerHTML = ...
//    + outer iframe textarea.se2_input_syntax 2개 sync
// 7. button "임시저장" click (R10 fullClick)
// 8. R14: "기업인증을 진행해 주세요" 모달 = 게시 단계만 차단, 임시저장은 성공
// 9. R12: https://www.jobkorea.co.kr/Corp/GiMng/List?KCFlag=4 → 임시저장 탭 → "임시저장 1" 카운터 + 카드 추출
//    (KCFlag=4 가 임시저장 필터, 카드 a 의 href 에서 GINo 추출)
```

### 3.3 LinkedIn RPS InMail 템플릿

기존 `linkedin-rps-jd-set-builder` SKILL 그대로 사용. 본 SKILL 은 그 SKILL 을 cascade 호출만:

```javascript
// 1. https://www.linkedin.com/talent/recruiter (사장님 chrome 세션 의존)
// 2. /talent/projects → 회사/포지션 키워드로 프로젝트 ID 매칭
//    (예: projectId=1728233460 for "뤼튼, 글로벌 그로스 마케터")
// 3. /talent/hire/{projectId}/discover/recruiterSearch/profile/{candidateId}/messages?project={projectId}&rightRail=composer
//    (임의 후보자 1명 = "placeholder", 본문 입력 후 Save as new 만)
// 4. input[aria-label="Message subject"] + [role="textbox"][aria-label="Compose a message"]
//    R7 한국어 직접 + R8 native setter / execCommand insertText
// 5. button[aria-label="Save as new template"] click (R10 fullClick)
// 6. input[aria-label="Message template name"] + radio[name="visibility-type"][value="HIRING_CONTEXT"]
//    (= "Anyone in my organization")
// 7. Save button click → toast "{template name} has been saved" 검증
//    R0 — Send 절대 금지
```

---

## 4. position-batch-flow 통합 (R20)

`tools/position-batch/orchestrator.mjs` 의 새 step:

```javascript
// tools/position-batch/steps/recruit-post.mjs
import { runRecruitPost } from "./recruit-post.mjs";

// orchestrator 의 step 정의:
{
  step: "recruit_post",
  parallel: false,                    // chrome 단일 인스턴스 — sequential
  before: async () => {
    await chromeGuard();              // R2 점유 검증
    await credentialCheck("saramin"); // R5 60일 회전 경고
    await credentialCheck("jobkorea");
  },
  run: async (position) => {
    const result = {
      linkedin: await registerLinkedInTemplate(position),
      saramin: await registerSaraminDraft(position),
      jobkorea: await registerJobkoreaDraft(position),
    };
    await sendResultEmail(result);    // R17 + R18
    return result;
  },
  recordTo: "position_batch_steps",   // step='recruit_post'
}
```

---

## 5. 사람 개입 게이트 (R4 명문화)

자동화 도중 다음 신호 발견 시 즉시 정지 + 사장님께 알림:

| 신호 | 대응 |
|------|------|
| input[type="password"] 입력 후 페이지에 "여러 번 실패 기록" 메시지 | R3 STOP. PW 변경 여부 확인 요청 |
| img[src*="captcha"] 또는 "그림문자" 텍스트 발견 | R3 STOP. 사장님 수동 캡차 입력 요청 |
| "기업인증을 진행해 주세요" (잡코리아) | R14. 사장님 수동 인증 안내. 임시저장은 진행 |
| 사장님 chrome 활성 탭에 ChatGPT/이력서/인재검색 발견 | R2 + R15. 새 탭 생성 |
| 사람인 "이전 공고 불러오기" 모달 자동 노출 | R11. ESC 또는 close 버튼 |

알림 형식 (Discord 또는 stdout):

```
[recruit-post-builder] STOP at {channel}/{step}
  reason: {captcha|2FA|biz-cert|owner-active}
  url: {current_url}
  next: 사장님이 {action} 후 "OK" 알려주시면 자동화 이어서 진행합니다.
```

---

## 6. 검증 + 결과 메일

각 채널 결과 카드:

| 필드 | 사람인 | 잡코리아 | LinkedIn |
|------|-------|---------|---------|
| status | saved / draft / blocked | saved / draft / blocked | saved / blocked |
| URL | /zf_user/jobs/view?rec_idx=... | /Corp/GiUp/View?GINo=... | /talent/hire/{projectId}/.../profile/{candidateId} (템플릿) |
| 본문 글자수 | 1,580~1,600 (R6 spec) | 1,900~2,100 | ≤1,892 (이름 치환 후 1,900) |
| 마감일 | 30일 후 권장 | 30일 후 권장 | — |
| 사장님 수동 후속 | 미완 필드 + 사전 확인 + 게시 | 기업인증 + 게시 | composer → 후보자 선택 → Send |

메일 spec — `scripts/send-3channel-registration-urls.mjs` (2026-05-29 라이브 검증된 패턴 그대로 재사용):

```javascript
// 발신 = 수신 = sangmokang@valueconnect.kr
// 제목 = "[등록 완료][JD Set Builder] {회사명} {포지션명} — 3채널 등록 URL"
// 본문 = HTML 카드 3개 + 사장님 수동 게시 가이드 + 글자수/마감일 뱃지
// transport = gmail-oauth, lock 파일 1회 보장
```

---

## 7. 학습 기록 (라이브 검증)

| 날짜 | 포지션 | 결과 | 비고 |
|------|--------|------|------|
| 2026-05-29 14:00~14:30 KST | 뤼튼 Global Growth Marketer (북미) | LinkedIn SAVED + 사람인 DRAFT (rec_idx=54026502) + 잡코리아 임시저장 1건 (서치펌 본문 + 직무명) | [[QA-258]] 잡코리아 캡차 발견 → 사장님 수동 로그인 후 자동화 재개 → 잡코리아 임시저장 추가 성공. 본 SKILL 첫 명문화 |

---

## 8. 관련 SKILL

- [[linkedin-rps-jd-set-builder]] — LinkedIn InMail 템플릿 등록 (본 SKILL 의 3.3 으로 cascade)
- [[saramin-talent-sourcing]] — 인재 검색 + 제안 발송 (본 SKILL 과 별도 흐름)
- [[jobkorea-talent-sourcing]] — 인재 검색 + 제안 발송 (본 SKILL 과 별도 흐름)
- [[position-batch-flow]] — 8단계 orchestrator (본 SKILL 의 R20 으로 통합)
- [[chatgpt-position-sourcing]] — ChatGPT 멀티탭 후보자 추천
- [[talent-search]] — 사람인/잡코리아/LinkedIn talent pool URL 메타 가이드

---

## 9. 부속 도구 (open, 다음 사이클)

[[QA-258]] 후속 작업 4건이 본 SKILL 의 R4/R5 를 실제 코드로 구현:

- [ ] `tools/automation-runtime/credential-loader.mjs` — env 파일 mtime + 60일 회전 경고 (R5)
- [ ] `tools/automation-runtime/login-gate.mjs` — 캡차/실패 감지 → 사장님 개입 게이트 (R4)
- [ ] `tools/automation-runtime/browser-selector.mjs` — claude-in-chrome list_connected_browsers wrap (R2/R15)
- [ ] saramin-talent-sourcing / jobkorea-talent-sourcing SKILL R3 갱신 — 단순 STOP → 사람 개입 게이트
