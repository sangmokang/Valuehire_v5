# Codex 스킬 동기화 — goal (2026-07-07)

## 현재 상태 (직접 확인)
- Codex CLI 0.142.5 는 `~/.codex/skills/<name>/SKILL.md` 를 네이티브로 읽는다. frontmatter(`name`/`description`) 형식은 Claude 와 동일. (확인: `~/.codex/skills/st/SKILL.md`)
- 현재 Codex 에는 3개만 존재(손으로 이름 바꿔 이식): `st`(=Claude `strict`), `ai-search`(=Claude `aisearch`), `weekly`(=Claude `weekly-update`). + `.system/`(Codex 자체 시스템 스킬, 건드리면 안 됨).
- Claude 저작 스킬 = 전역 `~/.claude/skills/*/SKILL.md`(디렉토리형) + 이 레포 `.claude/skills/*`, `skills/*`.
- 플러그인 스킬(`oh-my-claudecode:*`,`vercel:*`,`sc:*`,`codex:*`)은 `~/.claude/skills` 밖(플러그인)이라 이 동기화 대상 아님 — 자연히 제외됨.

## 핵심 질문
Claude 에 등록된 사장님 저작 스킬 전부를, 재실행 가능한 스크립트로 `~/.codex/skills/` 에 안전하게 미러링한다.

## 계약 (입출력 스펙 — SDD)
`sync_skills(sources: list[Path], dest: Path, *, force_aliases=False, dry_run=False) -> dict`
반환:
```json
{
  "copied":   ["skill-name", ...],
  "skipped":  [["name","reason"], ...],
  "collisions":[["name","kept_source","dropped_source"], ...],
  "classification": {"name": "full" | "partial"}
}
```
규칙(인수 기준, 기계 검사 가능):
1. 각 source 하위에서 **`SKILL.md` 를 가진 디렉토리만** 대상. 없으면 skip.
2. 이름이 `.` 로 시작하면 무시(→ `.system` 등 절대 안 건드림). dest 의 `.` 자식도 절대 삭제/수정 안 함.
3. 이미 손이식된 별칭 `{strict, aisearch, weekly-update}` 은 기본 skip(codex 의 st/ai-search/weekly 보존). `force_aliases=True` 면 복사.
4. 이름 충돌 시 **먼저 온 source 가 이김**, collision 기록.
5. 복사는 스킬 디렉토리 전체 미러(재실행 시 갱신+stale 제거), 단 `.git/node_modules/__pycache__/.pytest_cache/*.pyc` 제외.
6. 분류: SKILL.md 에 Claude 전용 마커(`claude-in-chrome`,`mcp__`,`Task(`,`subagent`,`oh-my-claudecode`,`Skill 툴/tool`) 있으면 `partial`(Codex 에선 절반만 동작), 없으면 `full`.
7. `dry_run=True` 면 아무것도 안 쓰고 결과만 계산.

## 적용 게이트 / 위험등급
- mixed(코드=sync.py+테스트, 문서=goal/README). **L2** — 로컬 `~/.codex` 쓰기(파괴적 아님, 게이트 2로 방어). 외부발송/로그인/제품코드 아님 → L3 아님.
- worktree: `worktrees/codex-skill-sync` (task/codex-skill-sync).

## 적대검증 정조준 항목
- `.system` 및 dest 의 `.`디렉토리를 실수로 지우는가(가드 테스트).
- dest escape / 경로 이탈.
- 재실행 idempotent + stale prune 가 dest 루트나 인접 스킬을 건드리는가.
- 별칭 skip 이 정확히 3개만인가.

## 비범위
- 각 SKILL.md 본문을 Codex 용으로 개작하지 않음(사장님 지시=그대로 복사). partial 라벨은 파일이 아니라 리포트에만.
- 플러그인 스킬 이식.

## 적대 검증 로그
(비워둠 — G→V1(Codex)→T 채운다)
