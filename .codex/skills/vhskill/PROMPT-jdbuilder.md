# Codex 붙여넣기 프롬프트 — jdbuilder / 포지션 등록 / 서치 실행강제

아래를 Codex CLI 프롬프트에 그대로 붙여넣으면, Claude Code와 동일한 규칙·가드·정식 러너로 동작한다.

---

너는 ValueHire 저장소에서 일한다. 아래 규칙을 무조건 따른다.

1. 사장님이 "해/가/등록해/발송해/진행해/포스팅해/돌려"라고 하면 그 문장이 전체 실행 OWNER_SIGNOFF다. 되묻지 말고 정식 러너로 끝까지 실행한다. "가도 될까요/어느 쪽으로 할까요" 금지. (AGENTS.md §0.15)
2. 완료 = 실제 등록/발송까지. 본문 작성·조회·dry-run·준비만 하고 멈추면 미완료(사고). 실행 증거(카드/토스트/message id)를 남긴다.
3. 스킬 실행은 `$vhskill <요청>` 로 한다 — .claude/skills, ~/.claude/skills 에서 맞는 스킬을 찾아 그 SKILL.md 를 이 저장소에서 그대로 따른다. (jd builder/포지션 등록 = jdbuilder)
4. 채용사이트 등록·발송은 정식 러너로만: `npm run position-batch:register:{saramin|jobkorea|linkedin}`, `npm run position-batch:send-offer`. raw CDP/즉석 스크립트로 사람인·잡코리아·링크드인을 직접 조작하지 않는다 — `.codex/hooks.json` 가드가 exit 2 로 막는다. 막히면 = 방법이 틀린 것이니 정식 러너로 갈아타 완주한다.
5. 회사 리서치 5요소(매출·창업연도·창업자·투자·주요제품)는 `company_research`(Supabase, 장애 시 로컬 SQLite 미러) → 본문은 `build-offer-bodies` + 게이트 경로로만. 모델이 본문을 즉석 조립하지 않는다.
6. 모든 브리핑은 쉬운 한국어 존댓말.

작업: <여기에 사장님 요청을 그대로 적는다. 예: "$vhskill jdbuilder 로 https://... 포지션을 4채널에 포스팅하라">

---

## 강제 메커니즘 (참고)
- `.codex/hooks.json` → `.claude/hooks/harness-dispatch.py`(Claude/Codex 공용) → `guards/*.py`.
- jdbuilder 가드가 raw CDP·즉석 등록 스크립트·제안 draft 를 exit 2 로 차단하고 정식 러너로 안내.
- Codex 최초 실행 시 hooks.json 신뢰 프롬프트가 뜨면 승인해야 훅이 활성화된다(`~/.codex/config.toml [hooks.state]`).
