---
name: ai-search
description: "Execute or inspect the Valuehire AI Search workflow. Use when the user says AI Search, Ai Search, search candidates, 후보자 서치, 포지션 서치, ClickUp 포지션으로 후보 찾기, or asks to run/debug/spec-check Valuehire candidate sourcing. This skill follows the spec-driven SOT in /Users/kangsangmo/Valuehire_v5: preflight, occupancy/captcha/login gates, JD intake, 5-axis keyword strategy, parallel Saramin/Jobkorea/LinkedIn RPS search, scoring, output contract, and Korean reporting. It prohibits ad-hoc searching, arbitrary candidate discovery, or any workflow that skips or weakens the SOT stages and gates."
---

# Valuehire AI Search

## ⛔ 공통 SOT 시작 게이트 (절대 생략 금지)

이 스킬이 발동되면 **작업·코딩·브라우저 조작·외부 쓰기 전에 먼저 기존 정의를 회수한다.**
이 게이트를 건너뛰면 SOT 위반이다.

반드시 먼저 읽고 보고:
- 루트 SOT: `CLAUDE.md`
- 작업 루프: `docs/harness.md`
- 관련 SOT: `docs/sot/`
- 이 스킬 참조: `references/spec-procedure.md`, `references/code-map.md`
- 기존 구현 진입점: `tools/multi_position_sourcing/` 아래 AI Search 실행·스코어링·브라우저·출력 경로
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
- 알람 폭탄 금지. 여러 후보·여러 포지션·여러 항목은 한 메시지 또는 한 댓글로 묶는다.
- `profile_url` 등 필수 URL/필드는 쓰기 직전 무결성 검사를 통과해야 한다.

Use this skill to run, explain, debug, or modify Valuehire AI Search. Treat the repo SOT as stronger than older loose `skills/search` instructions.

Default repo root: `/Users/kangsangmo/Valuehire_v5`. If the current workspace is a different Valuehire checkout, use that root and verify the same SOT files exist.

## First Moves

1. Read `references/spec-procedure.md`.
2. Run the SOT checker before live or code work:

```bash
python3 ~/.codex/skills/ai-search/scripts/ai_search_sot_check.py --repo /Users/kangsangmo/Valuehire_v5
```

3. For implementation/debugging, read `references/code-map.md` and then the exact repo files it points to.

Do not start from `skills/search/SKILL.md` alone. That file is a legacy/fresh-logic guide; the operating spec is `docs/sot/25-ai-search-execution-process.json`.

## Operating Rules

- Do not search on your own initiative. AI Search may start only from a user-provided position ID, ClickUp task URL, hiring URL, JD text, or an explicit instruction to run a specific stage.
- Do not run generic web search, portal search, ChatGPT Search, LinkedIn/Saramin/Jobkorea search, or candidate discovery before stage 0-4 have established scope, channel state, JD source, and keyword strategy.
- Do not replace the SOT with convenience judgment. If the SOT and a shortcut conflict, the SOT wins; if the tool path is unavailable, stop and report the blocker.
- Do not silently downgrade live search into unofficial manual search. If a required channel is `OCCUPIED` or `BLOCKED`, mark it that way and do not improvise around the gate.
- Use only Valuehire v5 for AI Search execution. Do not run v4 code or npm scripts.
- Follow `docs/sot/25-ai-search-execution-process.json` stage order unless the user explicitly limits the scope.
- Before portal actions, classify each channel as `READY`, `OCCUPIED`, or `BLOCKED`.
- If the owner is using Chrome, perform zero automation actions and resume only after it is clear.
- Auto-login all three protected portals from the configured secret store when logged out. Stop the affected channel only on a real captcha, 2FA, bot block, checkpoint, or LinkedIn multi-session lock. Do not bypass or repeatedly retry.
- Do not split channels by job type. Saramin, Jobkorea, and LinkedIn RPS are all considered for every role when live portal search is in scope.
- Do not auto-send proposals, email, InMail, or any Send/보내기 action.
- Do not report a candidate unless the output contract is satisfied: `profile_url`, `score`, `why_fit`, `profile_summary`.
- When AI Search or Humansearch results are recorded in ClickUp, use only FY26AI_Search list `901818680208`
  (`https://app.clickup.com/9018789656/v/li/901818680208`). Create/reuse one position parent Task and candidate
  Subtasks; run duplicate checks for the parent Task and each candidate `profile_url` before any create. Candidates
  without profile-save evidence (`screenshot`, `evidence_paths`, archive id, etc.) must not be registered.
- Report in short, plain Korean.

## Spec Stages

The live AI Search stage sequence is:

1. `0_preflight`: confirm v5 repo and Chrome/CDP path.
2. `1_occupancy_captcha_gate`: check captcha, multi-session, and login state first; classify channels.
3. `2_yield_resume`: pause during owner Chrome use, then resume.
4. `3_jd_intake`: use ClickUp JD first; supplement stale/missing JD from official hiring pages.
5. `4_keyword_strategy`: split JD into industry, role, skill/tool, experience, and exclude axes.
6. `5_channel_search`: search Saramin, Jobkorea, and LinkedIn RPS in parallel when ready.
7. `6_evaluation`: score by JD fit, school signal, job stability, and domain/tool fit.
8. `7_output_contract`: serialize only candidates with the required 4 fields; apply the FY26AI_Search ClickUp
   registration contract when ClickUp recording is in scope.
9. `8_jd_template_lane`: for new/open roles, check LinkedIn/RPS JD template state; never send.
10. `9_report`: report channel counts, template state, next keywords, artifact paths, and terminal reasons.

## When Work Is Limited

- If the user asks for a briefing or spec summary, do not run portals. Read SOT and summarize.
- If the user asks for strategy only, stop after stage 4.
- If the user asks for dry-run, do not write to ClickUp, Supabase, Discord, portal saves, or outreach. ClickUp duplicate
  checks/readback may still be required before any later live FY26AI_Search Task/Subtask registration.
- If the user gives no position/JD/source, ask for the missing input instead of searching generally.
- If live search is blocked, report which channel was blocked and why; do not call it “no candidates.”

## References

- `references/spec-procedure.md`: consolidated SOT, gates, and stage rules.
- `references/code-map.md`: related repo code, scripts, tests, and known missing/dead references.
