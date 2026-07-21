---
name: vhskill
description: Generic runner for any ValueHire Claude Code skill from inside Codex. Locate the matching skill under .claude/skills or ~/.claude/skills by the user's request/name and follow its SKILL.md faithfully in this repo. Use when asked to run a ValueHire skill by name (e.g. "$vhskill jdbuilder ...", "vhskill weekly-update 실행", "skill 역매칭 돌려", "스킬 jdbuilder 실행", "포지션 등록", "jd builder", "위클리 업데이트", "AI Search 돌려") without a dedicated Codex-native skill for it.
---

# vhskill — ValueHire 스킬 제네릭 브릿지 (Codex)

Hermes 의 `vh_skill_run`(`tools/hermes-agent/valuehire/tools.py`) 과 동일한 설계를 Codex 로 이식한 것.
스킬 이름을 하드코딩하지 않고, 사용자 원문 요청에 맞는 ValueHire 스킬을 스스로 찾아 그 `SKILL.md` 를
**이 저장소 안에서 그대로 따른다.** 안전 경계는 이 파일이 아니라 저장소의 `CLAUDE.md`/`AGENTS.md`
§0.2·§9 규칙과 `.claude/hooks/harness-dispatch.py` + `.claude/hooks/guards/*.py`(SOT-27) PreToolUse 훅이
담당한다 — Codex 도 cwd=저장소 루트라 동일 훅이 그대로 걸린다.

> 이 브릿지는 Codex 자체 Skills Hub(범용 마켓플레이스 스킬)와 다른, **ValueHire 채용업무 전용**
> Claude Code 스킬을 실행하기 위한 것이다. Codex 에 이미 네이티브 SKILL(`match`, `docsreview`,
> `gmail-resume-clickup-match`)이 있는 요청은 그 네이티브 스킬을 우선 사용한다.

## 절차

1. **스킬 탐색.** 사용자 요청/지목 이름에 맞는 스킬을 찾는다. 두 위치를 모두 나열해 후보를 고른다:
   - `.claude/skills/<name>/SKILL.md` (저장소 로컬, v4)
   - `~/.claude/skills/<name>/SKILL.md` (전역, v5)
   ```bash
   ls .claude/skills; ls ~/.claude/skills
   ```
   이름이 명시되면 그 이름을 우선한다. 아니면 각 후보 SKILL.md 의 `description`(frontmatter)을 읽고
   요청 의도에 가장 맞는 스킬 하나를 고른다. `jd builder`/`JD 빌더`/`포지션 등록`/`이직 제안 등록`은
   `jdbuilder` 로, `위클리`/`주간 회의록`은 `weekly-update` 로 매핑한다.

2. **정식 경로만.** 고른 스킬의 `SKILL.md` 를 처음부터 끝까지 읽고 그 절차·러너·SOT 문서를 그대로 따른다.
   즉석 raw 자동화(직접 CDP 스크립트, 임의 등록 스크립트, `create_draft` 등)로 우회하지 않는다
   (`CLAUDE.md` §0.2·§9). 스킬이 가리키는 `docs/sot/*`·`tools/*` 러너·`package.json` 스크립트를 쓴다.

3. **가드 존중.** PreToolUse 훅이 `guard` 차단 메시지를 주면 무시하지 말고 안내된 정식 경로로 다시 시도한다.
   두 번째도 막히면 멈추고 사유를 그대로 보고한다.

4. **되돌리기 어려운 행동 게이트.** 발송·등록·게시·금전처럼 되돌리기 어려운 행동은, 사용자 원문에
   `보내/발송/등록/게시/실행` 같은 명시적 지시가 있을 때만 진행한다(그 문장을 OWNER_SIGNOFF 로 본다).
   없으면 미리보기만 만들어 보여주고 확인을 구한다. 로그인·캡차·봇차단·스펙 충돌·기존 정의 미발견이면 멈추고 보고한다.

5. **결과 그대로 보고.** 요약·창작하지 말고 스킬이 만든 실제 목록·링크·글자수·메시지 id 를 그대로 보고한다.
   한국어 존댓말로 브리핑한다(`CLAUDE.md` Response Language).

## 비목표

- 스킬 로직을 이 파일에 복제하지 않는다(SOT 는 각 스킬의 SKILL.md 와 `docs/sot/*`).
- 안전 게이트를 이 파일에서 새로 정의하지 않는다(harness-dispatch + guards 가 SOT).
- 네이티브 Codex 스킬이 있는 요청을 가로채지 않는다.
