# codex_skill_sync — Claude 스킬을 Codex 로 동기화

Claude 에 등록된 사장님 저작 스킬(`~/.claude/skills`, 레포 `.claude/skills`, 레포 `skills`)을
Codex CLI 가 읽는 `~/.codex/skills/` 로 미러링한다. Codex 도 `SKILL.md` 형식이 Claude 와 동일하다.

## 쓰는 법
다른 PC에서는 repo clone 후 이 명령만 실행하면 repo에 포함된 skill 원본을 `~/.codex/skills/`로 설치한다.

```bash
make codex-sync-dry   # 모의실행: 무엇이 복사/보존/충돌인지 숫자만 확인(쓰지 않음)
make codex-sync       # 실제 동기화 → 끝나면 Codex 재시작
```
직접 호출도 가능:
```bash
python3 -m tools.codex_skill_sync.sync --dry-run
python3 -m tools.codex_skill_sync.sync            # 실제 반영
python3 -m tools.codex_skill_sync.sync --force-aliases   # st/ai-search/weekly 손이식본까지 덮어씀
```

## 원칙 (계약: `docs/engineering/codex-skill-sync-goal-2026-07-07.md`)
- `SKILL.md` 를 가진 디렉토리만 대상. dot 디렉토리(`.system` 등)는 절대 안 건드림.
- 손이식본(`strict→st`, `aisearch→ai-search`, `weekly-update→weekly`)은 기본 **보존**(skip). 덮어쓰려면 `--force-aliases`.
- 이름 충돌 시 **먼저 온 소스**가 이김(전역 → 레포 순).
- 재실행 미러(갱신 + 오래된 파일 제거). `.git/node_modules/__pycache__` 등 잡음 제외.

## 주의 — "부분동작(partial)"
Claude 전용 도구(크롬 자동조종 `claude-in-chrome`, 서브에이전트 `Task`, `Skill` 호출)에 의존하는
스킬은 Codex 에 **문구는 뜨지만 그 도구 단계는 안 돈다.** dry-run 이 어떤 스킬이 full/partial 인지 알려준다.
"그대로 복사"가 사장님 지시 — 그래서 SKILL.md 본문은 손대지 않고, full/partial 구분은 리포트로만 보여준다.
