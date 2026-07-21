# Gmail 실제 발송 — 디자인된 HTML, draft 절대 금지

> 사고 이력(2026-07-09): BISTelligence FDE/FSE 등록 때 `mcp__claude_ai_Gmail__create_draft`로 임시보관함에 평문을 넣고 끝냈다. SOT-10 §0 철칙 6 위반. 이 문서는 재발 방지용 유일 경로다.

## 정본 경로 (이것만 허용)

```
buildGmailOfferHtml(fields) / buildGmailOfferText(fields) / buildGmailOfferSubject(fields)
  = app/pipeline/_lib/gmailOfferEmail.ts (기존 정본 빌더, 코드 변경 불필요)
-> buildGmailOfferEmail(fields) -> { subject, html, text }
-> POST /api/pipeline/messages  { template_id: "job_offer", offer_fields: fields, to }
   (app/api/pipeline/messages/route.ts)
-> sendMessage({ subject, body: text, html, to })
   (app/pipeline/_lib/messageProviders.ts — multipart/alternative, text/html; charset="UTF-8")
-> Gmail API messages.send 실제 호출 — draft 아님
```

`GmailOfferFields` 계약(코드 확인됨, `app/pipeline/_lib/gmailOfferEmail.ts:13`): `{ companyName, positionName, greeting?, companyBrief, chargeWork, qualifications?, preferences? }`.

## 금지
- `mcp__claude_ai_Gmail__create_draft` — 이 스킬 범위에서 사용 금지(draft = "임시보관함 개소리", 사장님 명시 2026-07-09).
- `content_type: "text/markdown"` 또는 평문 단독 `sendMessage({ body })`(html 생략) — SOT-10 §0 철칙 6.
- 회사소개(companyBrief)에 company-research.md 5요소 미반영한 빈약한 본문.

## 자가검증 발송 (이 스킬로 실행 시 기본 모드)
후보자 실발송 전 자가검증 단계에서는 `to: "sangmokang@valueconnect.kr"`로 지정해 **실제 발송 버튼까지 실행**한다(사장님 명시 승인 — 자기 자신에게 보내는 것이므로 후보자 노출 없음). 발송 후 `messages.send` 응답의 `id`를 캡처하고, 가능하면 Gmail에서 실제 수신 렌더링을 재확인한다. 후보자 실제 발송은 `to`를 후보자 이메일로 바꾸기 전 별도 사장님 승인이 필요하다(R6, 발송 게이트).

## 검증 체크리스트 (T 기계판정)
- [ ] `tools/position-batch/lib/offer-readability-gate.mjs`의 `assertReadableGmailFields(fields)` 통과
- [ ] `html`에 `<!doctype html>` 또는 인라인 스타일 존재(디자인된 HTML 확인, 사장님 명시 "디자인된 것이어야 함")
- [ ] `html`에 SOT-10 §1 ①~⑤ 구조(인사/회사소개/JD원문/CTA/서명) 모두 존재
- [ ] JD 원문 전문이 `chargeWork`로 그대로 보존(요약 없음)
- [ ] CTA 링크 `https://valuehire.cc/resume` 텍스트 존재
- [ ] provider 응답이 draft id가 아니라 sent message id인지 확인(`messages.send` 응답 스키마: `id`, `threadId`, `labelIds`에 `SENT` 포함 — `DRAFT`면 실패)
- [ ] 실제 발송 후 Gmail 화면에서 문단·띄어쓰기·여백을 직접 확인. message id만으로 완료 금지.

## ⭐ 실행 러너 (2026-07-09 박제 — archaeology 금지, 한 명령 실발송)

세션 라우트(`/api/pipeline/messages`)는 로그인 쿠키가 필요해 느리다. **세션 없이 Gmail OAuth로 즉시 실발송**하는 정식 러너를 쓴다(같은 `.env.local` 자격 재사용 — draft 아님, `messages.send`):

```
node tools/position-batch/send-offer-email.mjs <fields.json> [--to=candidate@x] [--dry-run]
# 또는:  npm run position-batch:send-offer -- <fields.json> --to=...
```

- fields.json = `{ companyName, positionName, greeting, companyBrief(5요소), chargeWork(JD원문 1:1), qualifications?, preferences? }`
- 자격증명(.env.local, 코드와 동일): `SMTP_USER`(=from), `GMAIL_OAUTH_REFRESH_TOKEN`, `GMAIL_SEND_CLIENT_ID`, `GMAIL_SEND_CLIENT_SECRET`. **launchctl 아님 — .env.local 에 있다.**
- 성공 = 응답 `labelIds` 에 `SENT` 포함(+INBOX면 도착). `id` 를 완료 증거로 남긴다. `SENT` 없으면 실패.
- 자가검증은 `--to=sangmokang@valueconnect.kr`. 후보 실발송은 to를 후보 이메일로(사장님 승인 게이트 R6).
- ⛔ create_draft 금지(임시보관함=사고). 이 러너는 항상 실제 발송.
- 라이브 실증(2026-07-09): 비스텔리젼스 FSE → id `19f45a5f4a82ff79`, labels `[UNREAD,SENT,INBOX]`.
