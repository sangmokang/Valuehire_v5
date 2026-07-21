---
name: jdbuilder
description: 신규/기존 채용 포지션 1건을 사람인·잡코리아·LinkedIn InMail 템플릿·Gmail 4채널에 "이직 제안용"으로 등록/발송하는 유일한 진입점. 각 채널 글자수를 실측 상한까지 최대화해 JD를 풍성하게 담고, 회사 리서치 5필수요소(매출·창업연도·창업자·투자·주요제품)를 반드시 포함하며, Gmail은 draft가 아니라 디자인된 HTML로 실제 발송한다. 트리거 — "jdbuilder", "jd builder", "JD 빌더", "포지션 등록", "JD 등록", "신규 포지션 4채널 등록", "이직 제안 포지션 등록", "사람인 잡코리아 링크드인 지메일 등록". Codex CLI에서는 `$jdbuilder`로 동일하게 호출한다(`.codex/skills/jdbuilder/SKILL.md` 참조). 정본 스펙 = docs/sot/25-jd-builder-single-channel-spec.md(계약) + docs/sot/10-offer-message-body-spec.md(본문 구조). ⛔ 후보자 검색·제안발송(saramin-talent-sourcing/jobkorea-talent-sourcing), 채용공고 게시(recruit-post-builder), 후보자 화면에서 등록모달 채우기(pos-fill)는 이 스킬 범위 밖 — 각자 스킬로 라우팅한다.
---

# jdbuilder — 포지션 4채널 등록 단일 스킬

> 2026-07-09 — `position`/`position-register`/`position-batch-flow`/`linkedin-rps-jd-set-builder` 4개 스킬을 흡수 통합, `jd-builder`→`jdbuilder`로 개명(폴더명=스킬명 통일). 정본 계약: `docs/sot/25-jd-builder-single-channel-spec.md`. 이 문서와 SOT가 다르면 SOT가 맞다 — SOT부터 고친다.

## 0. 절대 규칙

| # | 규칙 |
|---|------|
| R0 | **JD 원문 사실 절대 왜곡·창작 금지.** 자격요건·근무조건 숫자를 다른 맥락(예: 내부 인재 매칭 검색 필터)에서 가져다 쓰지 않는다. JD에 없는 숫자면 쓰지 않는다. |
| R1 | **CTA 필수** — 모든 채널 마무리에 `docs/sot/10` §1④ 문구(`https://valuehire.cc/resume`)를 그대로 포함. 빠지면 미완성. |
| R2 | **개인화 필수** — 사람인/LinkedIn은 실제 발송 대상 후보자의 이름·현재회사·헤드라인을 인사말에 반영한다(범용 인사말 금지). |
| R3 | **Gmail은 실제 발송, draft 금지** — `mcp__claude_ai_Gmail__create_draft` 사용 금지. §4 경로만 허용. |
| R4 | **회사 리서치 5필수요소** — 매출·창업연도·창업자·투자·주요제품. `docs/sot/25` §2.1. |
| R5 | **글자수 최대화** — `docs/sot/25` §2. 실측 DOM maxlength 우선, 짧게 써서 여유 부리지 않는다. |
| R6 | **발송(Send)은 사람 수동** — 사람인/잡코리아 "등록"과 LinkedIn "템플릿 저장"까지만 자동. 후보자에게 나가는 최종 Send 클릭은 사장님 수동(Gmail 자가검증 발송은 예외 — §4). |
| R7 | **가독성 하드게이트 필수** — `docs/sot/28-offer-readability-harness.md`와 `tools/position-batch/lib/offer-readability-gate.mjs`를 통과하기 전에는 발송·등록 금지. raw JD 붙여넣기, `.slice(0,N)` 절단, `**About`/`•`/긴 산문 한 줄은 사고로 본다. |
| R8 | **fail-closed — 폴백 없음(2026-07-10)** — 채널 실행은 게이트 통과가 전제. offer_bodies 산출 없는 포지션은 등록/발송하지 않고 `offer-bodies-missing`으로 실패 기록(raw JD 폴백 금지). 회사 리서치 5요소 중 확인 3개 미만이면 `research-incomplete` 보류 → WebSearch로 채워 `npm run position-batch:upsert-company-research`로 upsert 후 본문 재생성(본문 직접 수정 금지). **모델의 즉석 payload 조립 금지** — 본문은 build-offer-bodies + 게이트(개인화 greeting·원문 보존 커버리지 0.5·날조 숫자 차단) 경로만. SOT-28 §5. |

## 1. 입력

```json
{ "company_name": "string", "position_name": "string", "jd_text": "string (원문 그대로, 최대 8000자 truncate)" }
```

ClickUp task에서 오면 `description`/`text_content`를 `jd_text`로 매핑.

## 2. 본문 생성

`tools/position-batch/lib/build-offer-bodies.mjs`를 그대로 재사용한다(코드 변경 없음 — SOT-10 프롬프트가 이미 §0 철칙을 강제). 출력 계약:

```json
{ "offer_comment": "...", "charge_work": "...", "company_brief": "...", "qualifications": "...", "preferences": "..." }
```

**추가 요구(2026-07-09)**: `company_brief` 생성 시 5필수요소(R4)가 있는지 스스로 체크하고, 없으면 회사 리서치를 먼저 수행(Supabase `companies.research` 조회 → miss 시 WebSearch)해 채운다. 6개 미만이면 등록 전 사장님 보고(SOT §2.1).

## 3. 채널 실행 — 상세 절차는 references/ 참조

| 채널 | 실행 절차 |
|---|---|
| 사람인 | [references/saramin.md](references/saramin.md) |
| 잡코리아 | [references/jobkorea.md](references/jobkorea.md) |
| LinkedIn InMail | [references/linkedin.md](references/linkedin.md) |
| Gmail | [references/gmail.md](references/gmail.md) |
| 회사 리서치 5요소 | [references/company-research.md](references/company-research.md) |

각 채널 실행 전 반드시 해당 reference를 읽는다 — 즉석 생성 금지(R0, 이번 사고 재발 방지 핵심).

## 4. Gmail 실제 발송 (R3)

```
buildGmailOfferEmail(fields) -> {subject, html, text}
-> POST /api/pipeline/messages { template_id: "job_offer", offer_fields, to }
-> sendMessage({ html })  // multipart/alternative, 실제 발송(Gmail API messages.send)
```

자가검증 모드에서는 `to: "sangmokang@valueconnect.kr"`로 지정해 실제 발송 버튼까지 실행하고 받은 편지함에서 렌더링을 확인한다. 후보자 실발송은 별도 사장님 승인 필요.

## 4.1 가독성 검수 (R7)

모든 채널 payload는 실제 쓰기 전에 다음을 통과해야 한다.

```
node -e "import('./tools/position-batch/lib/offer-readability-gate.mjs').then(m=>...)"
```

- 한 줄 180자 안팎 초과 금지.
- `[회사 소개]`, `[주요 업무]`, `[자격 요건]`, `[우대 사항]`처럼 헤더로 나눌 것.
- `- ` 불릿을 사용하고 `•`, `**About`, raw JD 문단 덤프 금지.
- 플랫폼 저장값이 잘리지 않았는지 실제 화면/DOM 값으로 확인할 것.
- Gmail은 message id만으로 완료가 아니며, 읽히는 HTML/TEXT 산출물을 함께 검수할 것.

## 5. 배치 모드

ClickUp `FY26ClientsPosition` active 포지션 순회는 `tools/position-batch/orchestrator.mjs`(`CANONICAL_STEPS`)를 그대로 호출한다 — 별도 스킬 불필요, 이 스킬이 배치의 단건 실행 절차를 제공한다.

## 6. 완료 보고 형식

```
🟢 JD Builder 등록 완료 — {회사}/{포지션}
- 사람인: 등록 완료 / 글자수 offerComment N자 chargeWork N자 (실측상한 대비 X%)
- 잡코리아: 등록 완료 / 글자수 N자
- LinkedIn: 템플릿 저장(Anyone in my organization) / N자(1899 hard cap 대비 X%)
- Gmail: 실제 발송 완료(to: sangmokang@valueconnect.kr) / message id: ...
- 회사 리서치 5요소: 매출 ✅ 창업연도 ✅ 창업자 ✅ 투자 ✅ 주요제품 ✅ (또는 ※미확인 표기)
- 적대검증: G/V1/V2 3자 대조표 첨부
```
