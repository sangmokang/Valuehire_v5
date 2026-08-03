# goal — `claude -p` 유료 키 유출 차단 (2026-08-03)

## ① 현재 상태 (증거)

`claude -p` 를 subprocess 로 부르는 지점 3곳 중 **1곳만** 유료 키를 제거하고 있었다.

| 호출부 | 키 제거 (변경 전) |
|---|---|
| `tools/multi_position_sourcing/matching_score_contract.py:389` | ✅ `:377` `env.pop("ANTHROPIC_API_KEY", None)` |
| `tools/multi_position_sourcing/llm_keywords.py:341` | ❌ 부모 환경 상속 |
| `tools/multi_position_sourcing/fleet_worker.py:1038` `_run_claude()` | ❌ `env=None` → 부모 환경 상속 |

문서·스킬에는 `env -u ANTHROPIC_API_KEY claude -p` 규율이 널리 적혀 있다
(`skills/st/SKILL.md:54`, `docs/ai-search/reservoir-gmail-clickup-match-goal-prompt-2026-06-19.md:40` 등).
**규율은 문서에만 있고 코드가 강제하지 않았다.**

## ② 근본 원인

`claude -p` 는 Max 구독으로 도는 무료(0원) 경로다. 그런데 부모 환경에 `ANTHROPIC_API_KEY` 가
있으면 CLI 가 그 키를 집어 **유료 API 과금 경로로 조용히 넘어간다.**
실패도 경고도 없어서 **청구서가 올 때까지 모른다.** 이 저장소의 fail-closed 철학 위반.

## ③ 인수 기준 (AC · 1개)

**If `claude -p` 를 subprocess 로 호출하면, then 시스템은 `ANTHROPIC_API_KEY` 가 제거된
환경으로 호출해야 한다 — 호출부 전부.**

- 검증: `./verify.sh` (exit 0) / 단위: `pytest tests/test_claude_p_api_key_strip.py`
- counter-AC (가짜 완료):
  - ① 테스트가 mock 호출 여부만 보고 **실제 전달된 env** 를 검사하지 않으면 가짜.
  - ② `llm_keywords` 만 고치고 `fleet_worker` 의 `env=None` 경로를 남기면 가짜.
  - ③ 호출자 환경을 통째로 덮어써 다른 변수(`VALUEHIRE_MACHINE` 등)가 유실되면 가짜 —
    **키만 빼고 나머지는 보존**해야 한다.

## ④ 게이트 진행

| 게이트 | 결과 |
|---|---|
| 2 | RED `720fe41` — 키가 그대로 실려가는 것을 재현 |
| 3 | GREEN `444febf` — 호출부 전부에서 키 제거 |
| 3.5 | 배선: 프로덕션 진입점 `fleet_worker._run_claude()`(함대 워커 잡 실행) 및 `llm_keywords.claude_keyword_client`(운영 키워드 생성) — 테스트 전용 경로 아님 |
| 3.6 | `d49e185` — 전수 가드를 소스 디렉터리 전체로 확장 |
| 4a | **3384 passed, 2 skipped, 4 xfailed, 138 subtests passed / exit 0** |
| 4b | 아래 §적대 검증 |

## ⑤ 구현

`fleet_worker._claude_subprocess_env(env)` 신설:
`env is None` 이면 `os.environ` 사본, 아니면 주어진 env 사본에서 **키 하나만** 제거.
`_run_claude` 의 모든 분기(shell 경유·cancel watch·Windows shim)가 이 함수를 거친다.
`llm_keywords` 도 동일 방식으로 `os.environ` 사본에서 키만 제거해 전달.

## ⑥ SOT 체크리스트

- `docs/ai-search/reservoir-gmail-clickup-match-goal-prompt-2026-06-19.md:40`(비용 헌법) 준수 방향.
- **SOT 수정 불필요** — 기존 규율을 코드가 따라간 것이지 규율을 바꾸지 않았다.

## ⑦ 비범위

- `skills/`·`.claude/skills/` 아래 파이썬은 전수 가드 범위 밖(`tools`/`scripts`/`apps`/`ops` 만 훑음).
  현재 그 폴더에 **실제 호출은 없다** — `skills/disearch/scripts/audit_disearch.py:145` 등은
  `'["claude", "-p", prompt]'` 라는 **문자열을 검사하는 감사 스크립트**이지 호출이 아니다.
  (오히려 가드 범위에 넣으면 그 문자열 때문에 오탐이 난다.) 미래에 스킬이 직접 호출하게 되면
  가드 범위를 넓혀야 한다 — **알려진 사각지대로 명시**한다.

## ⑧ 롤백

`git revert <merge-sha>`. 키를 빼는 것 외에 동작 변경이 없어 되돌려도 부작용 없음.

## ⑨ 영향 반경

`claude -p` 를 부르는 모든 경로(함대 워커 잡 실행, 키워드 생성, 채점). 잘못되면 LLM 호출이
실패해 그 작업이 멈춘다. 다만 변경은 "환경변수 하나 제거"뿐이고, 나머지 변수 보존을
`test_run_claude_preserves_caller_env_and_drops_only_the_key` 가 강제한다.

---

## 적대 검증 로그

### G — Codex (구현자)
브랜치 `task/apikey-strip-live`, 커밋 `720fe41`(RED) → `444febf`(GREEN) → `d49e185`(가드 확장).

### V — Claude (검증자, 구현과 분리)

**1. counter-AC 대조**

| counter-AC | 확인 방법 | 결과 |
|---|---|---|
| ① 실제 env 검사하나 | `tests/test_claude_p_api_key_strip.py:50` `assert "ANTHROPIC_API_KEY" not in env` | ✅ mock 호출 여부가 아니라 **전달된 env dict** 를 검사 |
| ② `env=None` 경로 처리 | `test_run_claude_default_env_strips_api_key`(:113) + shell/cancel/shim 3경로 개별 검사 | ✅ 4경로 전부 |
| ③ 다른 변수 보존 | `test_run_claude_preserves_caller_env_and_drops_only_the_key`(:130), `must_keep` 대조(:52) | ✅ |

**2. 뮤테이션 점검 (가짜 GREEN 차단)**

| 일부러 깨뜨린 것 | 결과 |
|---|---|
| `llm_keywords` 의 키 제거 → `dict(os.environ)` 로 무력화 | **1 failed** ✅ |
| `fleet_worker._claude_subprocess_env` → `dict(source)` 로 무력화 | **4 failed** ✅ |

둘 다 원복 확인(`git status` 청결).

**3. 사각지대 재수색 (V가 독립 수행)**

저장소 전체에서 `"claude", "-p"` argv 생성부를 전수 grep한 결과, 실제 호출부는
`llm_keywords.py:346`·`matching_score_contract.py:389`·`fleet_worker`(base_args 방식) 뿐이고
**전부 처리됨**. `skills/` 아래 히트는 전부 문자열 검사(감사 스크립트) — §⑦에 명시.

**판정**: G·V 일치. counter-AC 3종 전부 방어되고 뮤테이션이 정상 적발되므로 통과.
