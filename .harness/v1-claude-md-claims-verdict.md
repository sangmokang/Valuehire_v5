# V1 적대검증 — CLAUDE.md 개편 주장 판정

- 대상: Claude(생성자 G)가 사장님께 보고한 C1~C15
- 검증자: V1 (독립 적대검증)
- 저장소: /Users/kangsangmo/Desktop/Valuehire_v5 @ main 27bcbd8
- 일자: 2026-08-03
- 원칙: 호의적 해석 금지. 각 주장을 깨려고 시도하고, 그 시도를 본문에 남긴다.

---

## [C1] 판정: OVERSTATED

**주장**: "프로젝트 CLAUDE.md(73줄) 중 **절반**이 '코드를 두 번 깐다'는 중복이다."

**증거**:
- `wc -l CLAUDE.md` → `73`
- 중복 구간 실측 (`CLAUDE.md` 라인 번호 직접 확인):
  - `CLAUDE.md:33-40` — SOT 불변식 5 "내가 만든 코드는 믿지 않는다 — 두 번 깐다" (8줄)
  - `CLAUDE.md:46-60` — "## 5번 규칙 풀이 — 왜 두 번 까는가" 섹션 전체 (15줄)
  - `CLAUDE.md:66-67` — 작업 방식 첫 불릿 "…두 번 깨기 → 확인 → 올리기" (2줄)
- 합계 **25줄 / 73줄 = 34.2%**. 섹션 구분선·공백(44,45,61,62,63)까지 관대하게 포함해도 **30줄 = 41.1%**.

**반증 시도**:
1. "절반"을 문자 수 기준으로 재면 달라지는가? → 아니다. 오히려 더 불리하다. SOT 불변식 1~3(라인 29~31)이 한 줄에 300~600자짜리 장문 단락이라 문자 기준으로는 중복 비중이 **더 낮아진다**(전체 6,911바이트 중 중복 구간은 약 1,900바이트 ≈ 27%).
2. "두 번 깐다"의 의미 범위를 최대한 넓혀 `docs/harness.md` 참조 언급(40행, 67행)까지 중복으로 셀 수 있는가? → 40행·67행은 이미 위 계산에 포함돼 있다. 더 늘릴 여지 없음.
3. 반대로 중복이 **없다**고 주장할 수 있는가? → 불가. 33-40과 46-60은 같은 4단계 절차(작게 자른다 → 내가 깬다 → Codex Rescue가 깬다 → 과거 지시 회수)를 두 번, 두 어투로 반복한다. 실질 중복은 명백히 존재한다.

**정정안**: "73줄 중 약 25줄(34%)이 '두 번 깐다' 절차의 반복 서술이다 — 같은 4단계가 SOT 불변식 5(33-40), 별도 해설 섹션(46-60), 작업 방식 불릿(66-67) 세 곳에 중복돼 있다." (방향은 맞지만 '절반'은 과장.)

---

## [C2] 판정: CONFIRMED

**주장**: "지금 CLAUDE.md에는 저장소 구조 지도가 없고, 빌드/테스트 명령도 없다."

**증거**:
```
$ grep -nE 'verify\.sh|pytest|npm |make |tools/|tests/|apps/|scripts/' CLAUDE.md
(없음)
```
- 실제 최상위 디렉터리는 9개: `apps artifacts docs ops scripts skills supabase tests tools` — CLAUDE.md 어디에도 등장하지 않는다.
- CLAUDE.md가 언급하는 경로는 전부 문서(`docs/sot/26…json`, `docs/harness.md`, `docs/prompts/…`, `docs/sot/29·33`)뿐이다.

**반증 시도**:
1. `CLAUDE.md:69`가 "실제로 검사를 돌려보고"라고 하니 명령이 있는 셈 아닌가? → 아니다. **어떤 명령인지 적혀 있지 않다**. `./verify.sh`라는 문자열이 파일에 0회 등장한다. 새 세션이 CLAUDE.md만 읽으면 검사를 어떻게 돌리는지 모른다.
2. `docs/harness.md`를 따르라고 했으니 간접적으로 있는 것 아닌가? → 간접 참조는 "CLAUDE.md에 있다"와 다르다. 주장은 "CLAUDE.md에 없다"이고, 그것은 참이다.

**정정안**: 불필요. 정확한 서술이다.

---

## [C3] 판정: CONFIRMED

**증거**:
```
$ find tools/multi_position_sourcing -name '*.py' | wc -l
89
$ find tools/multi_position_sourcing -name '*.py' -exec cat {} + | wc -l
34479
```

**반증 시도**:
1. `__pycache__`나 vendor 사본이 부풀린 것 아닌가? → `find`는 `.py`만 세고, 해당 디렉터리에 `__pycache__/*.py`는 없다(`.pyc`만). 벤더 디렉터리도 없다.
2. "핵심 엔진"이라는 수식이 과장인가? → 아니다. 이 디렉터리에 로그인(`portal_login.py` 831줄), 브라우저 구동(`portal_worker.py` 2,019 / `portal_live_check.py` 3,963 / `session_guard.py` 2,583), 채점(`match.py`, `matching_score_contract.py`), 발송 게이트(`auto_send.py`), 함대(`fleet_worker.py` 1,898)가 모두 들어 있다. 저장소 파이썬 로직의 중심이 맞다.

**정정안**: 불필요.

---

## [C4] 판정: OVERSTATED (핵심 결론은 참, 부수 서술이 부정확)

**주장**: "CI에는 numpy가 없다. 검사는 **pytest + playwright만** 돈다. 따라서 임베딩·코사인은 순수 파이썬으로 써야 한다."

**증거 — numpy 없음(참)**:
- `requirements-dev.txt` 전문: `pytest`, `psycopg[binary]`, `playwright==1.60.0`, `discord.py==2.4.0`, `audioop-lts`(py3.13+ 한정). **numpy 없음.**
- numpy import 전수조사:
```
$ grep -rn "import numpy\|from numpy" --include='*.py' . | grep -v node_modules
.claude/skills/slack-gif-creator/core/gif_builder.py:13:import numpy as np
.claude/skills/slack-gif-creator/core/frame_composer.py:11:import numpy as np
.codex/skills/slack-gif-creator/core/gif_builder.py:13
.codex/skills/slack-gif-creator/core/frame_composer.py:11
```
  → 4건 전부 Anthropic 배포 스킬 번들(`slack-gif-creator`) 사본이고, `tests/`가 import 하지 않으므로 CI에서 실행되지 않는다.
- 코드가 이 제약을 명시적으로 기록하고 있다 — `tools/multi_position_sourcing/embed.py:6`:
  > "CI에는 numpy가 없으므로 임베더/cosine은 순수 파이썬이다."

**증거 — "pytest + playwright만"은 부정확**:
- `.github/workflows/verify.yml:11-27`에 **postgres:16 서비스 컨테이너**가 떠 있고 `TEST_DATABASE_URL`이 주입된다. `requirements-dev.txt`에 `psycopg[binary]`, `discord.py`도 있다.
- 즉 CI 검사 환경은 `pytest + playwright + psycopg + discord.py + 살아있는 postgres`다.

**반증 시도**:
1. numpy가 transitively 들어오지 않는가? → `playwright`, `psycopg[binary]`, `discord.py`, `pytest` 중 numpy 의존은 없다. `pip install -r requirements-dev.txt`만 실행하므로(verify.yml:36) numpy는 설치되지 않는다.
2. `.venv-playwright` 로컬 환경에는 numpy가 있어서 로컬만 통과하고 CI에서 깨지는 함정이 있는가? → 이것이 이 규칙의 실제 존재 이유다. 규칙 자체는 유효하고 필요하다.
3. slack-gif-creator가 CI에서 collect될 위험은? → `verify.sh`가 `pytest tests/`로 경로를 한정한다. `.claude/skills/`는 수집 대상이 아니다. 위험 없음.

**정정안**: "CI 검사 환경에는 **numpy가 없다**(`requirements-dev.txt` 전체가 pytest·psycopg·playwright·discord.py뿐). 그래서 임베딩·코사인 유사도는 순수 파이썬으로 쓴다 — 이 제약은 `tools/multi_position_sourcing/embed.py:6`에 이미 명시돼 있다. 단 '**pytest + playwright만**'은 틀렸다: CI는 postgres 16 컨테이너를 띄우고 `TEST_DATABASE_URL`을 주입하며 psycopg·discord.py도 설치한다(`.github/workflows/verify.yml:11-36`)."

---

## [C5] 판정: CONFIRMED

**증거** — `verify.sh:7-24` 전문 확인:
```bash
for cand in ".venv-playwright/bin/python" ".venv/bin/python" "python3" "python"; do
  if "$cand" -c "import pytest" >/dev/null 2>&1; then PY="$cand"; break; fi
done
...
"$PY" -m pytest tests/ -q
```
- `docs/harness.md:102` — `| make verify / ./verify.sh | 4a | 테스트 전체, exit 0 == GREEN |` (게이트 4a의 유일한 기계 판정 명령)
- `docs/harness.md:110` — "스킬·문서의 기계 단언도 **같은 `./verify.sh`(pytest) 안에** 계약 테스트로 얹는다."
- 이 저장소에는 `.venv-playwright`(playwright 설치본)와 `.venv` 둘 다 존재할 수 있어, 맨손 `pytest`는 어느 인터프리터가 잡히느냐에 따라 결과가 달라진다.

**반증 시도**:
1. "자동 탐색"이 실제로는 하드코딩 4개 후보 순회일 뿐 아닌가? → 맞다. 하지만 "pytest를 가진 인터프리터를 찾아 쓴다"는 서술은 정확하다. 못 찾으면 exit 2로 fail-closed하고 설치 방법까지 안내한다(verify.sh:17-20).
2. `pytest`를 직접 부르면 정말 다른 결과가 나오는가? → 그렇다. `verify.sh`는 `tests/` 경로를 고정하고 `-q`를 붙인다. 맨손 `pytest`는 루트에서 실행되면 `.venv-playwright/lib/.../site-packages` 하위까지 수집을 시도할 수 있다(그 안에 `discord/types/embed.py` 등이 실재함 — find 결과로 확인).
3. `verify.sh`가 `set -e` 없이 `set -uo pipefail`만 쓰는 게 결함 아닌가? → 결함 아니다. 의도적이다. pytest exit code를 `rc`로 잡아 그대로 반환해야 게이트 4a가 성립한다.

**정정안**: 불필요.

---

## [C6] 판정: OVERSTATED

**주장**: "전역 `~/.claude/CLAUDE.md`는 442줄이며 'RULE 3: NEVER do code changes directly - delegate to executor'라고 명시한다. 이는 이 저장소의 하니스와 **정면 충돌**한다."

**증거 — 사실 부분(참)**:
- `wc -l ~/.claude/CLAUDE.md` → `442`
- `~/.claude/CLAUDE.md:50` — `RULE 3: NEVER do code changes directly - delegate to executor` (RULE 1~5는 48~52행)

**증거 — '정면 충돌'을 깨는 결정적 반증**:
같은 파일의 **최상단**이 이 충돌을 이미 명시적으로 해결하고 있다.
- `~/.claude/CLAUDE.md:1` — `<!-- HARNESS:START -->`
- `~/.claude/CLAUDE.md:2` — `# 0. 최고 권위 규칙 — Harness (모든 프로젝트 전역)`
- `~/.claude/CLAUDE.md:8`(HARNESS 블록 마지막 문단) — **"이 Harness 규칙은 아래 oh-my-claudecode 오케스트레이션 지침과 충돌할 경우 절차(게이트·워크트리)에 한해 우선한다. 단, 사용자의 명시적 지시가 항상 최우선이다."**
- 즉 파일 구조가 `HARNESS:START…HARNESS:END` → `OMC:START…`이고, 앞 블록이 뒷 블록보다 우선한다고 **자기 안에 적혀 있다**.

또한 RULE 3과 하니스 게이트 2·3은 논리적으로도 배타가 아니다:
- `docs/harness.md:62` (게이트 3) — "RED→GREEN 최소 변경만. 규모 목표 파일 1~5 / diff 50~300줄."
- 게이트는 **어디서(워크트리) / 어떤 순서로(RED 먼저) / 무엇으로 판정하는지(`./verify.sh`)**를 규정할 뿐, **누가 타이핑하는가**(메인 에이전트 직접 vs executor 서브에이전트)는 규정하지 않는다. executor 서브에이전트가 워크트리 안에서 RED를 먼저 커밋하고 GREEN을 만들어도 게이트는 전부 만족된다.

**반증 시도**:
1. 그래도 실무상 충돌하지 않는가? → 마찰은 있다. 하니스는 "생성자 G와 검증자 V1을 분리"하라고 하고(게이트 4b, `docs/harness.md:78`), OMC는 "모든 코드 변경을 executor에 위임"하라고 한다. 둘 다 따르면 위임 계층이 2단(executor + 검증자)이 된다. 하지만 이건 **비효율**이지 **모순**이 아니다.
2. RULE 4("NEVER complete without Architect verification")가 게이트 4b(Codex Rescue 2차 적대검증)와 충돌하는가? → 오히려 같은 방향이다. 둘 다 독립 검증자를 요구한다.
3. 반대로 "충돌 없음"을 완전히 주장할 수 있는가? → 아니다. `~/.claude/CLAUDE.md:8`의 우선 선언은 **"절차(게이트·워크트리)에 한해"**로 범위가 좁다. 위임 여부는 '절차'인가 '수행 방식'인가가 문언상 애매하다. 그래서 "충돌 없음"이 아니라 "**정면 충돌은 아니고, 우선순위가 이미 선언돼 있으며, 남는 것은 해석 여지**"가 정확한 판정이다.

**정정안**: "전역 규칙서는 442줄이고 `~/.claude/CLAUDE.md:50`에 'NEVER do code changes directly - delegate to executor'가 있다. 다만 **정면 충돌은 아니다** — 같은 파일 최상단 Harness 블록(`~/.claude/CLAUDE.md:2-8`)이 '충돌 시 절차(게이트·워크트리)에 한해 Harness가 우선한다'고 이미 선언해 두었다. 남는 문제는 충돌이 아니라, 위임 여부가 '절차'에 포함되는지 문언상 애매해 매번 해석이 필요하다는 점이다."

---

## [C7] 판정: FALSE (추론 자체가 성립하지 않음)

**주장**: "최근 커밋 60개를 보면 executor 위임 방식을 쓴 흔적이 없다."

**증거 — 전제가 무너진다**:
```
$ git log -60 --pretty=format:'%H %s%n%b' | grep -icE 'executor|subagent|delegat|agent'
1
$ git log -60 --pretty=format:'%b' | grep -iE 'executor|subagent|delegat'
- 결함 ⑩: 채널별 파이프라인을 ThreadPoolExecutor(채널당 1 스레드)로 실제
```
→ 유일한 hit이 **`ThreadPoolExecutor`라는 파이썬 클래스명**이다. 커밋에서 위임 여부를 grep으로 판별하려는 시도가 오탐 하나를 낳고 끝났다.

**증거 — 실제로 커밋에 남는 것**:
```
$ git log -60 --pretty=format:'%b' | grep -i 'co-authored-by' | sort | uniq -c | sort -rn
  39 Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
  32 Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
  16 Co-authored-by: Claude Opus 5 (1M context) <noreply@anthropic.com>
   1 Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
   1 Co-authored-by: Claude Sonnet 5 <noreply@anthropic.com>
```
→ **모델 이름만 남고 에이전트 역할은 남지 않는다.** executor 서브에이전트(Sonnet)가 커밋해도, 메인 세션(Opus)이 커밋해도 트레일러 형식은 동일하다. 실제로 Sonnet 5 트레일러가 2건 섞여 있는데, 이것이 executor 위임의 흔적인지 단순히 그 세션 모델이 Sonnet이었는지 **커밋만으로는 구별 불가능**하다.

**반증 시도**:
1. 위임 여부를 커밋에서 알아낼 다른 신호가 있는가? → 찾아봤다. 커밋 author는 전부 `Sangmo Kang`(git config 고정), committer도 동일. 브랜치명(`task/<NAME>`)은 하니스 워크트리 규칙의 산물이지 위임 여부와 무관. 커밋 시각 간격도 서브에이전트 병렬 여부를 증명하지 못한다.
2. "흔적이 없다"가 우연히 참일 가능성은? → 참일 수도 있지만 **이 증거로는 알 수 없다.** 위임은 세션 transcript(`~/.claude/projects/*/`)에 Task 툴 호출로 남지 git 이력에는 남지 않는다. 즉 이 주장은 잘못된 곳을 봤다.

**정정안**: "커밋 이력으로는 executor 위임 여부를 판정할 수 없다 — 서브에이전트가 만든 커밋과 메인 세션이 만든 커밋의 트레일러가 동일하기 때문이다(`Co-Authored-By: Claude <model>`만 남고 역할은 안 남는다). 위임 여부를 확인하려면 세션 transcript의 Task 툴 호출을 봐야 한다." 원 주장은 **근거 없는 단정**이므로 사장님 보고에서 빼야 한다.

---

## [C8] 판정: 사실 부분 CONFIRMED / '판단을 낭비한다' 부분은 부분적으로 CONFIRMED (측정 아닌 사례 근거)

**주장**: "전역 CLAUDE.md 442줄이 매 대화마다 컨텍스트에 주입되어 토큰과 판단을 낭비한다."

**증거 — 주입은 실측 확인**:
- `wc -c ~/.claude/CLAUDE.md` → 18,298 바이트 / 442줄. 프로젝트 CLAUDE.md는 6,911 바이트 / 73줄.
- 주입 사실은 **이 세션 자체가 증거**다. 이 검증 세션의 `<system-reminder>` 블록에 `~/.claude/CLAUDE.md` 전문과 `Valuehire_v5/CLAUDE.md` 전문이 그대로 실려 있다(claudeMd 컨텍스트). 즉 세션 시작 시 무조건 로드된다.
- 대략 토큰: 18,298바이트 ≈ 5,000~6,000토큰(영문+표 위주). 프로젝트분 6,911바이트 ≈ 2,500~3,500토큰(한글 위주). 합계 매 세션 약 8,000~9,000토큰 고정 비용.

**증거 — '판단을 흐린다'가 관측된 실제 사례가 저장소 안에 있다**:
`tools/multi_position_sourcing/matching_score_contract.py:379-382` 주석 (2026-08-01 라이브 사고 기록):
> "이 호출은 '에이전트에게 일을 시키는' 것이 아니라 순수 추출 함수다. 기본 시스템 프롬프트를 그대로 두면 **프로젝트·전역 CLAUDE.md 와 스킬이 실려서 추출 요청을 작업 지시로 읽고 되묻는다** — JSON 이 없으니 그 후보가 통째로 버려진다(2026-08-01 라이브). 그래서 지침을 대체하고, 저장소 밖 빈 디렉터리에서 실행한다."

→ CLAUDE.md 주입이 실제로 LLM 출력을 망가뜨려 **후보가 통째로 버려지는 라이브 장애**를 냈고, 그 대응으로 `--system-prompt` 교체 + `cwd=tempdir` 회피 코드가 들어가 있다(`matching_score_contract.py:377-394`).

**반증 시도**:
1. "판단을 낭비한다"는 측정 가능한 주장인가? → 문자열 그대로는 **측정 불가**다. A/B 실험도, 벤치마크도 없다. 이 부분만 놓고 보면 UNVERIFIABLE이다.
2. 그런데 반례가 아니라 **실증 사례**가 나왔다 → 위 주석. 다만 이 사례는 "인간과 대화하는 세션"이 아니라 "LLM을 순수 추출 함수로 부르는 서브프로세스"에서 일어났다. 대화 세션에서 442줄이 판단을 흐린다는 직접 증거는 아니다. 그래서 "부분적으로 CONFIRMED".
3. 토큰 낭비를 부정할 수 있는가? → 없다. 프롬프트 캐싱이 비용을 줄여도 컨텍스트 창은 실제로 차지한다.

**정정안**: "전역 442줄 + 프로젝트 73줄이 매 세션 컨텍스트에 자동 주입된다(약 8~9천 토큰 고정). '판단을 흐린다'는 벤치마크로 측정된 바 없지만, 저장소 안에 실제 피해 기록이 있다 — `matching_score_contract.py:379-382`가 'CLAUDE.md가 실려서 추출 요청을 작업 지시로 읽고 되묻는' 2026-08-01 라이브 장애를 기록하고 그 회피 코드를 담고 있다."

---

## [C9] 판정: 그룹별 혼재 — 5개 그룹 중 2개는 정확, 2개는 부분 오류, 1개는 명백한 오류

전제 확인: 나열된 19개 파일 전부 `tools/multi_position_sourcing/` 아래 실재한다(MISSING 0건). 파일명 존재 자체는 CONFIRMED. 문제는 **역할 라벨**이다.

### 그룹 1 "3사 로그인·세션" — 판정: 대체로 CONFIRMED (1건 부정확)
| 파일 | 실제 역할 (docstring/코드 근거) | 라벨 적합? |
|---|---|---|
| `portal_login.py` (831줄) | 채널별 로그인 수행 + ready_check. `models.Channel` 기반 | ✅ |
| `portal_autologin.py` (219줄) | 사람인 기업회원 자동로그인 URL·플로우, `_has_security_challenge` 감지 | ✅ |
| `session_guard.py` (2,583줄) | "로그인 세션가드 — exact target, 사람 로그인 대기, 안전 keepalive"(:1). 사람 점유 감지 fail-closed 포함 | ✅ |
| `login_barrier.py` (345줄) | **로그인을 하지 않는다.** "로그인 선행 장벽 **단일 검증기**"(:1) — `~/.valuehire/login_receipts/<channel>.json` **영수증 파일을 검증**한다. 모델 출력 문구를 신뢰하지 않는 fail-closed validator | ⚠️ 부정확 |

**정정안(그룹 1)**: "3사 로그인·세션 — 로그인 수행(`portal_login.py`, `portal_autologin.py`), 세션 유지·사람 점유 양보(`session_guard.py`), **로그인 완료 영수증 검증**(`login_barrier.py` — 로그인을 하는 게 아니라 '했다'는 주장을 파일로 검증하는 fail-closed 게이트)"

### 그룹 2 "브라우저 조종(CDP)·라이브 점검" — 판정: 대체로 CONFIRMED (1건 부정확)
| 파일 | 실제 역할 | 라벨 적합? |
|---|---|---|
| `raw_cdp.py` (1,120줄) | "raw CDP 단일타깃 드라이버 — 사장님 9222 탭 과다 환경에서 connectOverCDP 전체 attach hang 회피"(:1) | ✅ |
| `humansearch_cdp_run.py` (947줄) | "humansearch CDP 순회 러너"(:1). 다만 **채점까지 오케스트레이션**한다 — "검색결과 카드 수집 → 프로필 열기 → CapturedProfile 빌드 → 채점"(:4) | ✅(단 채점 파이프라인도 겸함) |
| `portal_live_check.py` (3,963줄) | **단순 라이브 점검이 아니다.** `live_readiness_payload`, `init_session_key_payload`, `init_portal_credentials_payload`, `init_discord_webhook_payload`, `supabase_access_check_payload`, `supabase_schema_proof_payload`, `pacing_policy_proof_payload`, `safe_weekly_counts_payload`, `run_live_search` — **라이브 준비 진단 + 자격증명/웹훅 초기화 + Supabase 접근·스키마 증명 + 주간 집계 + 실제 라이브 검색 실행**까지 담은 3,963줄 종합 CLI | ⚠️ 심하게 축약됨 |
| `portal_worker.py` (2,019줄) | docstring 없음. 실제: CDP 엔드포인트 탐색·검증(`discover_local_chrome_cdp_endpoints`, `resolve_managed_channel_cdp_endpoint`, `find_verified_channel_target`) + **크롬 프로필 락**(`ProfileLock`, `validate_portal_profile_root`) + **사장님 유휴 증명**(`proved_owner_idle_seconds`) + 검색 생존감시(`SearchLivenessMonitor`) | ⚠️ "브라우저 조종"보다 넓음 |

**정정안(그룹 2)**: "브라우저 조종(CDP) — 단일탭 저수준 드라이버(`raw_cdp.py`), 검색결과 순회·채점 러너(`humansearch_cdp_run.py`), **크롬 엔드포인트 탐색·프로필 락·사장님 유휴 증명**(`portal_worker.py`), **라이브 준비 진단·자격증명 초기화·Supabase 증명·라이브 검색 실행 종합 CLI**(`portal_live_check.py`, 3,963줄로 이 디렉터리 최대 파일)"

### 그룹 3 "후보 채점·매칭" — 판정: OVERSTATED, `grouping.py`는 FALSE
| 파일 | 실제 역할 | 라벨 적합? |
|---|---|---|
| `match.py` (104줄) | "저수지 모델 — match() + 재랭킹(단계 5). JD를 임베딩해 세그먼트 내 top-K 코사인 → scoring.py로 2차 정렬"(:1-5) | ✅ |
| `matching_score_contract.py` (593줄) | "Deterministic Stage 4… the only layer allowed to calculate the final 0-100 score and action band"(:1-5) | ✅ |
| `embed.py` (174줄) | "프로필 임베딩 적재(**단계 4**)… pgvector(profile_embeddings)에 적재"(:1-3). **채점이 아니라 색인/적재**다 | ⚠️ 인접 단계 |
| `grouping.py` (111줄) | **후보와 무관하다.** `infer_role_family(position)`, `group_positions(positions) -> tuple[PositionGroup,...]` — **채용 포지션(JD)을 직군·연차·단계로 묶는** 모듈. 입력이 `Position`이지 후보가 아니다 | ❌ **오류** |

**정정안(그룹 3)**: "후보 채점·매칭 — 벡터 top-K 추림 + 재랭킹(`match.py`), 최종 0~100점·액션밴드 결정론 계산(`matching_score_contract.py`), 프로필 임베딩 색인 적재(`embed.py`, 채점 전 단계). **`grouping.py`는 여기 속하지 않는다** — 후보가 아니라 **채용 포지션(JD)을 직군·연차별로 묶는** 모듈이다."

### 그룹 4 "발송 게이트" — 판정: `dedup.py`는 FALSE
| 파일 | 실제 역할 | 라벨 적합? |
|---|---|---|
| `auto_send.py` (360줄) | "3사 제안 자동발송 게이트 + 원장 — SOT28"(:1). fail-closed·킬스위치·pending 선기록 | ✅ |
| `inmail_precheck.py` (351줄) | "발송 전 기계 체크리스트" STOP 5종 + 보고 1종(:1-16) | ✅ |
| `jd_outreach.py` (242줄) | "아웃리치 JD 컴포저 — 길이 캡 가드(PC-G1) + InMail 본문 조립(PC-G2)"(:1-3). **게이트 겸 조립기** | ⚠️ 절반은 조립기 |
| `dedup.py` (62줄) | **발송과 무관하다.** `canonical_profile_url()` + `SeenProfile` — 프로필 URL 정규화·중복 제거. 사용처: `embed.py:18`, `dry_run.py:14` (**수집·색인 단계**) | ❌ **오류** |

**결정적 반증**: `auto_send.py`는 `dedup.py`를 **import 하지 않는다**.
```
$ grep -n "dedup" tools/multi_position_sourcing/auto_send.py
84:    if not _strict_int(policy.get("dedupe_window_days")) …
304:                window_days=policy["dedupe_window_days"],
```
→ 발송 중복 방지는 `dedup.py`가 아니라 **자체 원장(ledger)의 `dedupe_window_days`**로 한다. 이름이 비슷할 뿐 다른 모듈이다. 파일명만 보고 묶은 전형적 오류.

**정정안(그룹 4)**: "발송 게이트 — SOT28 자동발송 판정·원장(`auto_send.py`), 발송 전 기계 검문 STOP 5종(`inmail_precheck.py`), 본문 조립 + 글자수 캡 가드(`jd_outreach.py`). **`dedup.py`는 여기 속하지 않는다** — 수집·색인 단계의 프로필 URL 정규화 모듈이며(`embed.py:18`, `dry_run.py:14`에서만 쓰임) `auto_send.py`는 이 파일을 import조차 하지 않는다. 발송 중복 방지는 원장의 `dedupe_window_days`가 담당한다."

### 그룹 5 "3대 머신 함대·Discord 명령" — 판정: CONFIRMED (경로 주의 1건)
| 파일 | 실제 역할 | 라벨 적합? |
|---|---|---|
| `fleet_worker.py` (1,898줄) | "함대 워커 — 자기 머신 큐를 폴링해 `claude -p` 로 스킬 잡을 실행"(:1) | ✅ |
| `fleet_dispatch.py` (248줄) | "함대 Discord 명령 디스패처… 인가 통과한 fleet-* 인보케이션을 작업 큐로"(:1-3) | ✅ |
| `job_queue.py` (652줄) | "함대 작업 큐 — Supabase jobs/account_locks 클라이언트"(:1) | ✅ |
| `discord_*.py` | `tools/multi_position_sourcing/`에는 `discord_routing.py`(425줄), `discord_briefing.py`, `discord_hr1.py`. **핵심 게이트웨이는 다른 디렉터리에 있다**: `scripts/discord_direct_gateway.py`, `scripts/discord_command_listener.py`, `apps/aisearch/core/discord_notify.py` | ⚠️ 경로 누락 |

**정정안(그룹 5)**: 라벨은 정확하다. 다만 `discord_*.py` 와일드카드는 오해를 부른다 — Discord 진입점은 `tools/multi_position_sourcing/`(라우팅·브리핑)과 `scripts/`(직결 게이트웨이·리스너), `apps/aisearch/core/`(알림) **세 곳에 흩어져 있다.**

---

## [C10] 판정: OVERSTATED (파일 수 미세 오류, 네이밍 '관례'는 명백한 과장)

**주장**: "`tests/`는 pytest **160개 이상** 파일이고, **인수 기준별 `test_<기능>_ac<N>_*.py` 네이밍 관례**를 따른다."

**증거**:
```
$ ls tests/ | grep -c '^test_.*\.py$'
159
$ find tests -name '*.py' | wc -l
159
$ ls tests/ | grep -cE '_ac[0-9]'
10
```
→ **159개**(160 미만). `_ac<N>` 포함 파일은 **10개 = 6.3%**.

`_ac<N>` 10개 전체:
```
test_aisearch_ac1_boolean.py      test_aisearch_ac6_admin_api.py
test_aisearch_ac2_portal_search.py test_aisearch_ac7_intervention.py
test_aisearch_ac3_pagination.py    test_aisearch_ac8_banner.py
test_aisearch_ac4_score_gate.py    test_aisearch_ac9_draft.py
test_aisearch_ac5_dual_record.py   test_discord_bot_console_ac1.py
```
→ 그중 9개가 **`aisearch` 한 기능 하나**에서 나왔다. 나머지 1개(`test_discord_bot_console_ac1.py`)는 주장된 형식 `test_<기능>_ac<N>_*.py`의 **꼬리 `_*`조차 없다**(`ac1`으로 끝남). 즉 주장된 정확한 패턴을 따르는 파일은 **9개 = 5.7%**, 그것도 단일 기능 배치의 산물이다.

**반증 시도**:
1. `tests/` 하위 디렉터리에 더 있는가? → `tests/__pycache__`, `tests/fixtures` 둘뿐이고 테스트 파일 없음. 159가 전부다.
2. `conftest.py`를 더하면 160이 되는가? → `find tests -name '*.py'`가 159로 `ls`와 같으므로 `tests/conftest.py`는 없다. 160에 도달하지 못한다.
3. '관례'를 "권장되는 규범"으로 읽으면 참 아닌가? → `docs/harness.md`를 전수 검색했으나 `test_<기능>_ac<N>` 네이밍을 규정한 문장은 없다. 게이트 2는 "인수 기준 1개"를 요구할 뿐 파일명 규칙을 정하지 않는다. **문서에도 없고 코드에서도 6%다** — 어느 기준으로도 '관례'가 아니다.

**정정안**: "`tests/`에는 pytest 파일 **159개**가 있다(하위 디렉터리 없이 평평한 구조). 인수 기준을 파일명에 박는 `_ac<N>` 형식은 **10개(6%)뿐**이고 그중 9개가 `aisearch` 한 기능 배치에서 나왔다 — **관례가 아니라 일부 사례**다. 지배적 실제 관례는 `test_<모듈명>.py`(예: `test_job_queue.py`, `test_humansearch_skill.py`)다."

---

## [C11] 판정: OVERSTATED (발동 조건 전부 생략)

**주장**: "훅이 실제로 막는다 — 미커밋 변경을 남기고 응답을 끝내려 하면 Stop 훅이 저지하고, 증거 없는 완료 보고도 1턴 저지된다."

**증거 — 훅은 실재하고 등록돼 있다**:
- `.claude/settings.json` `Stop` 훅: `stop-evidence-gate.py` 실행 → `rc=99`면 `exit 2`로 승격.
- `.claude/hooks/stop-evidence-gate.py:BLOCK_EXIT = 99`

**증거 — 그러나 조건부다. 세 겹의 게이트가 있다**:

**(1) 미커밋 차단은 `strict` 마커가 유효할 때만 작동한다.**
`judge()` 흐름(`stop-evidence-gate.py`):
```python
marker_path = find_marker(payload.get("cwd", "."))
if marker_path is None:
    return None          # ← 마커 없으면 무조건 통과
```
- 마커 = **메인 레포**의 `.claude/strict-active.json`. 파일이 없으면 **아무것도 막지 않는다.**
- 마커 수명주기는 러너가 소유: 생성 `npm run wt`, 해제 `npm run wt:done`(docstring "H3").
- 추가 통과 조건들 — 하나라도 걸리면 **fail-open(통과)**:
  - `payload.get("stop_hook_active")` → 통과 (재시도 턴은 무조건 통과, 무한루프 방지)
  - 마커·payload 양쪽 `session_id`가 있고 다르면 → 통과 (남의 작업)
  - `created_at`이 naive(타임존 없음) → 통과
  - 미래 5분 초과 또는 24시간(TTL) 경과 → 통과
  - `worktree`가 절대경로가 아니거나 디렉터리가 아니면 → 통과
  - 그 worktree가 git 최상위가 아니면 → 통과
  - `git status --porcelain` 실패 또는 clean → 통과
  - **`main()`의 모든 예외 → `return 0` 통과**
- 즉 **차단은 좁은 교집합에서만** 일어난다. 파일 자신이 docstring에 명시: *"그 외 모든 모호·예외는 fail-open(exit 0) — 최악의 실패 모드는 전 세션 잠금이다."*

**(2) "증거 없는 완료 보고" 차단은 fleet 잡 세션 전용이다.**
```python
def fleet_job_violation(payload):
    if not (os.environ.get("VH_BUSY_TASK") or "").strip():
        return None      # ← 일반 세션은 무조건 통과
```
- 환경변수 `VH_BUSY_TASK`(워커가 주입)가 있을 때만 검사한다. 사장님이 직접 쓰는 대화 세션에서는 **작동하지 않는다.**
- 작동하더라도 정규식 휴리스틱: `_FLEET_DONE_RE`(완료|끝났|마쳤|모두 처리|done)가 매치되고 `_FLEET_EVIDENCE_RE`(FLEET_SEARCH_RECEIPT:|N건|N명|잡 #N|영수증|paused_for_human|실패|중단)가 **하나도** 없을 때만. "3건 처리" 같은 숫자 하나만 있어도 통과한다.

**(3) 차단의 실질은 "저지"가 아니라 "1턴 계속 프롬프트"다.**
- 파일 docstring: *"이 게이트는 '유효 마커 + 미커밋 잔존' 종료에 **한 턴 계속 프롬프트**를 넣는 장치다(공식 사양상 `stop_hook_active` 재시도 턴은 통과 — 무한루프 방지가 우선)."*
- 즉 **한 번 밀어낼 뿐, 두 번째 시도는 무조건 통과한다.** "막는다"는 표현은 지속적 차단을 연상시켜 과장이다.

**(4) 주장에서 아예 빠진 세 번째 기능이 있다**: R2 질문 금지 게이트(`question_violation`). strict 마커가 유효하면 미커밋 여부와 **무관하게**, 마지막 응답이 확인 질문("~할까요?")으로 끝나면 1턴 저지한다. 허용 예외는 2FA·캡차·본인확인·파괴적/비가역 확인뿐(`_QUESTION_ALLOW_RE`).

**반증 시도**:
1. 마커 없이도 막히는 경로가 있는가? → 있다, 딱 하나. `fleet_job_violation`은 마커 검사보다 **먼저** 실행되어 마커와 무관하다. 하지만 그것도 `VH_BUSY_TASK` env가 필요하다. 일반 대화 세션은 두 경로 모두 열려 있다.
2. 그래도 "실제로 막는다"는 참 아닌가? → 조건이 맞으면 참이다. 문제는 조건을 하나도 안 적어서 **"항상 막힌다"로 읽힌다**는 점이다. 실제로는 `npm run wt`로 마커를 안 걸면 이 훅은 존재하지 않는 것과 같다.

**정정안**: "Stop 훅(`.claude/hooks/stop-evidence-gate.py`, `.claude/settings.json`에 등록)이 있다. 단 **항상 막지 않는다**:
- 미커밋 차단은 `npm run wt`로 `.claude/strict-active.json` 마커를 건 strict 작업 세션에서만. 마커가 없거나 24시간 지났거나 세션 ID가 다르거나 판정 중 예외가 나면 전부 통과(fail-open — 설계 의도가 '전 세션 잠금 방지').
- 증거 없는 완료 차단은 `VH_BUSY_TASK` 환경변수가 있는 **함대 워커 잡 세션 전용**이다. 사장님이 직접 쓰는 세션에는 적용되지 않는다.
- 차단의 실질은 **1턴 계속 프롬프트**다 — 재시도 턴(`stop_hook_active`)은 무조건 통과한다.
- 주장에 빠진 기능: strict 세션에서 확인 질문("~할까요?")으로 턴을 끝내는 것도 1턴 저지한다."

---

## [C12] 판정: 대체로 CONFIRMED (괄호 안 'ANTHROPIC_API_KEY 제거'는 3곳 중 1곳뿐)

**주장**: "LLM 호출은 `claude -p`를 쓴다 (ANTHROPIC_API_KEY 제거, Max 요금제로 0원)."

**증거 — `claude -p` 호출부는 실재한다(3곳)**:
| 위치 | 코드 | API 키 제거? |
|---|---|---|
| `tools/multi_position_sourcing/llm_keywords.py:341` | `["claude", "-p", "--model", model, prompt]` | ❌ 없음 (부모 env 상속) |
| `tools/multi_position_sourcing/matching_score_contract.py:389` | `["claude", "-p", "--model", model, "--system-prompt", …, prompt]` | ✅ `matching_score_contract.py:377` — `env.pop("ANTHROPIC_API_KEY", None)` |
| `tools/multi_position_sourcing/fleet_worker.py:1038` `_run_claude()` | `claude -p` 실행(레포 루트) | ❌ 없음 — `env=None이면 부모 환경 상속(기존과 동일)` |

- `llm_keywords.py:9` 주석: *"운영은 `claude_keyword_client`(`claude -p`)로 라이브."*
- `llm_keywords.py:332` docstring: *"운영용 LLM 클라이언트 — 로컬 `claude -p` 호출(**비용 헌법: 저가 모델 기본**)."* → 기본 `model="haiku"`.
- `dry_run.py:301`: *"라이브 배선: 기본적으로 boolean 채널에 LLM X-ray 쿼리를 주입한다(claude -p, **비용 0원**)."*

**증거 — 키 제거는 문서·스킬에는 널리 적혀 있으나 코드 강제는 1곳뿐**:
```
docs/ai-search/reservoir-gmail-clickup-match-goal-prompt-2026-06-19.md:40
  "ANTHROPIC_API_KEY 경유(유료) 금지 — 호출 시 키 비운다."
skills/st/SKILL.md:54 · .codex/skills/st/SKILL.md:60 · .claude/skills/weekly-update/SKILL.md:19
  "env -u ANTHROPIC_API_KEY claude -p …"
docs/engineering/*.verdict.json (3건)  "env -u ANTHROPIC_API_KEY claude -p …"
```
→ 규율은 문서·스킬·검증기록에 널리 존재하지만, **파이썬 코드에서 실제로 키를 비우는 곳은 `matching_score_contract.py:377` 단 한 줄**이다.

**반증 시도**:
1. "문서에만 존재한다"고 판정할 수 있는가? → **불가.** `claude -p` 자체는 3곳에서 실제 subprocess로 호출된다. 문서만이 아니다.
2. 나머지 2곳도 실질적으로 0원 아닌가? → 사장님 셸에 `ANTHROPIC_API_KEY`가 없으면 그렇다. 하지만 **코드가 보장하지 않는다**. 어느 환경에서 키가 설정되면 `llm_keywords.py`·`fleet_worker.py` 경로는 조용히 유료 과금으로 흘러간다. 이 저장소의 fail-closed 철학과 어긋나는 실제 구멍이다.
3. 이것이 새 CLAUDE.md에 규칙으로 들어가면 오해를 낳는가? → 그렇다. "제거한다"고 단정하면 이미 그렇게 되어 있다고 읽힌다.

**정정안**: "LLM 호출은 `claude -p`를 쓴다(기본 모델 haiku — 비용 헌법). 호출부는 `llm_keywords.py:341`, `matching_score_contract.py:389`, `fleet_worker.py:1038` 세 곳. **`ANTHROPIC_API_KEY`를 코드에서 실제로 비우는 곳은 `matching_score_contract.py:377` 하나뿐**이고 나머지 둘은 부모 환경을 그대로 상속한다 — 규칙으로 적을 거라면 '제거한다'가 아니라 '**세 호출부 모두 키를 비워야 한다(현재 1/3만 준수)**'라고 적어야 사실이다."

---

## [C13] 판정: FALSE (해당 문구의 규칙이 저장소에 없고, 기계 강제도 없다)

**주장**: "SOT 드리프트 금지 — 코드 변경이 SOT에 적힌 동작을 바꾸면 같은 PR에 SOT 수정을 **동봉해야 머지 가능**하다."

**증거 — 그런 규칙 문장이 없다**:
```
$ grep -n "드리프트\|drift\|SOT 수정\|동봉" docs/harness.md
(0건)
$ grep -rn "같은 PR에 SOT\|SOT 동봉\|SOT 수정을 같은" docs/ *.md .claude/
(0건)
```
- `CLAUDE.md`(73줄) 전문에도 그런 문장 없음.
- "드리프트"라는 단어는 저장소에 20여 건 나오지만 전부 **다른 뜻**이다:
  - `docs/sot/31-fleet-run-reliability.md:33` — "머신별 **자격증명** 드리프트"
  - `docs/ai-search/…-2026-06-17.md:53` — "로그인 **셀렉터** 드리프트"
  - `docs/engineering/reservoir-harvest-driver-goal-2026-07-04.md:10` — "**경로** 드리프트"
  - `docs/prompts/strict-decompose-tdd-ladder-prompt-2026-07-19.md:12` — "별도 스킬 = 드리프트 재발 경로"

**증거 — 유사하되 훨씬 좁은 규칙은 실재한다**:
- `docs/sot/32-nl-shell-routing.md:3` — *"어휘·라우팅표·금지사항의 단일 출처는 JSON 이고… 둘이 어긋나면 **JSON 이 이긴다**(가드 **H-NL4** 가 드리프트를 차단한다)."*
- `docs/sot/32-nl-shell-routing.md:121` / `docs/prompts/discord-nl-shell-routing-goal-2026-07-22.md:164` — H-NL4 = "SOT 32 JSON 계약과 코드 어휘(`loci`/`verbs`)의 드리프트" 차단.
- → **SOT 32(NL 셸 라우팅) 하나에 한정된 가드**이지, 전 저장소 규칙이 아니다. SOT 문서는 22~33까지 18개 파일인데 나머지에는 대응 가드가 확인되지 않는다.

**증거 — 기계 강제 없음**:
- CI 워크플로는 `.github/workflows/verify.yml` **하나뿐**이고, `pip install -r requirements-dev.txt` → `./verify.sh`(= `pytest tests/`)가 전부다. PR 내용에 SOT 파일이 포함됐는지 검사하는 단계가 **없다**.
- `verify.sh`도 diff를 보지 않는다 — 테스트만 돌린다.
- `.claude/settings.json` 훅은 PreToolUse 2개 + Stop 1개뿐이고, 셋 다 PR/SOT 동봉과 무관하다.
- `Makefile`의 `ship:`은 verify → push → PR이고, SOT 동봉 검사를 하지 않는다.

**반증 시도**:
1. `tests/test_skill_sot_preflight_gate.py`가 강제하는 것 아닌가? → 확인했다. 이 테스트가 검사하는 것은 **SKILL.md 파일 안에 "## ⛔ 공통 SOT 시작 게이트" 문단과 `CLAUDE.md`·`docs/harness.md`·`docs/sot/`·"기존 구현 진입점"·"새 파일" 문구가 들어 있는가**다(REQUIRED_SNIPPETS). 대상은 `skills/position-registration/SKILL.md`, `skills/humansearch/SKILL.md`, `~/.codex/skills/ai-search/SKILL.md` 3개. **"코드가 바뀌면 SOT도 같은 PR에"와는 다른 검사**다.
2. `tests/test_hermes_retirement_contract.py` 같은 SOT 계약 테스트가 있으니 강제 아닌가? → 개별 SOT 문서의 내용을 고정하는 계약 테스트는 있다. 하지만 그건 "SOT 내용이 유지되는지"이지 "코드 변경 시 SOT를 함께 고쳤는지"가 아니다. **코드 diff와 SOT diff의 동반 여부를 보는 검사는 하나도 없다.**
3. 관행으로는 지켜지고 있지 않은가? → 관행일 수는 있으나, 주장은 "**머지 가능**"이라는 강제 표현을 썼다. 강제 장치가 없으므로 그 표현은 거짓이다.

**정정안**: "이 규칙은 현재 저장소에 **없다**. 유사한 것은 SOT 32(NL 셸 라우팅) 한 건에 붙은 H-NL4 가드뿐이고(`docs/sot/32-nl-shell-routing.md:3,121`), 그것도 JSON↔코드 어휘 한정이다. CI(`verify.yml`)·훅(`.claude/settings.json`)·`make ship` 어디에도 'SOT 동봉 없으면 머지 불가'를 검사하는 장치가 없다. 새 CLAUDE.md에 넣고 싶다면 **'규칙으로 새로 도입한다'고 명시**하고, 기계 강제를 원하면 별도 테스트(예: 변경 파일 목록 대조)를 같은 작업으로 만들어야 한다 — 없는 강제를 있다고 쓰면 SOT-30이 금지한 과장 표기다."

---

## [C14] 판정: CONFIRMED

**주장**: "새 스킬을 만들면 그 스킬의 계약 테스트를, 근거 인용 문서를 만들면 참조-존재 테스트를 같은 커밋에 넣어야 한다."

**증거 — 규칙 문장이 실재한다**:
- `docs/harness.md:64` — **"자기확장 규칙: 새 대상을 추가하면 그 대상의 verify 단언 + 픽스처를 **같은 커밋에** 추가한다."**
- `docs/harness.md:65` — **"새 스킬 → 그 스킬 계약 테스트. 새 근거-인용 문서 → 그 문서 참조-존재 테스트."**
- `docs/harness.md:56` — 스킬 산출물 판정 기준: "계약검사 실패(frontmatter·트리거·참조경로 부재) → 스킬 계약 테스트 GREEN"
- `docs/harness.md:57` — 문서 판정 기준: "깨진 태그 0·**근거 코드경로 실존**·끊긴 앵커 0"
- `docs/harness.md:110` — "스킬·문서의 기계 단언도 같은 `./verify.sh`(pytest) 안에 계약 테스트로 얹는다."

**증거 — 그런 테스트가 실제로 존재한다(14개)**:
```
tests/test_claude_skills_tracked.py        tests/test_matching_prompt_contract.py
tests/test_codex_skill_sync.py             tests/test_reservoir_doc.py
tests/test_hermes_retirement_contract.py   tests/test_search_skill_stability.py
tests/test_humansearch_skill.py            tests/test_skill_reference_integrity.py
tests/test_jdintake_skill.py               tests/test_skill_sot_preflight_gate.py
tests/test_learning_curriculum_doc.py      tests/test_sot_distrust_doublecheck_doc.py
tests/test_linkedin_session_skill_contract.py
tests/test_login_skill_contract.py
```
→ 스킬 계약 테스트(`*_skill*.py`, `*_skill_contract.py`)와 문서 참조-존재 테스트(`test_skill_reference_integrity.py`, `test_learning_curriculum_doc.py`, `test_reservoir_doc.py`, `test_sot_distrust_doublecheck_doc.py`) 양쪽 다 실재한다.
- `tests/test_skill_sot_preflight_gate.py:19-25` 실물 확인: `REQUIRED_SNIPPETS`로 SKILL.md 안의 필수 문단 존재를 단언한다 — 전형적 계약 테스트.

**반증 시도**:
1. 이 테스트들이 **모든** 스킬을 커버하는가? → 아니다. `test_skill_sot_preflight_gate.py`는 3개 SKILL.md만 대상으로 한다. 저장소에는 스킬이 훨씬 많다. 즉 **규칙은 있고 사례도 있지만 전수 커버는 아니다.**
2. 그렇다면 OVERSTATED로 내려야 하는가? → 아니다. 주장은 "**만들면 넣어야 한다**"는 **당위 규칙의 존재**를 말한 것이지 "모든 기존 스킬에 테스트가 있다"가 아니다. 규칙(`harness.md:64-65`)도 실재하고 이행 사례(14개)도 실재한다.
3. C13과의 차이? → C13은 규칙 문장 자체가 저장소에 **없었다**. C14는 `docs/harness.md:64-65`에 **글자 그대로** 있다. 명확히 갈린다.

**정정안**: 불필요. 근거를 붙이면 더 좋다 — "`docs/harness.md:64-65`(자기확장 규칙). 이행 사례 14건은 `tests/test_*_skill*.py`·`test_skill_reference_integrity.py` 등."

---

## [C15] 판정: OVERSTATED

**주장**: "커밋 메시지는 한국어이고 결과 중심이다."

**증거**:
```
$ git log -100 --pretty=format:'%s' > /tmp/c100.txt; wc -l → 99 (마지막 줄 개행 없음, 실제 100건)
$ grep -cP '[가-힣]' /tmp/c100.txt → 56
```
→ 한글이 **하나라도** 포함된 커밋 제목 = **56/99 ≈ 57%**. 나머지 **43건(43%)은 한글이 0글자**다.

한글 0건 샘플(실제 출력):
```
task/keyword group isolation clean (#271)
task/portal launchd enable clean (#270)
docs: add self-contained aisearch-zero completion prompt (#256)
fix(humansearch): reuse live authenticated LinkedIn Talent target (#252)
Merge pull request #250 from sangmokang/task/aisearch-ac6-admin-api-client
feat(login): owner-explicit takeover (AC-A) + login top-priority yield (AC-B) (#247)
test(aisearch-ac8): RED — V1 defects (attach race cancel, strict banner typing) (5 failed, 10 passed)
feat(aisearch-ac4): GREEN enforcing gate — BelowThresholdError + register_if_eligible
fix(#184): fail closed on WinPC agent readiness
test(#184): RED cleanup paused HR-1 jobs on abort
… (총 43건)
```

**반증 시도**:
1. Merge 커밋을 빼면 비율이 오르는가? → 오른다. 43건 중 Merge 커밋이 10건. 제외하면 한글 비율 56/89 ≈ 63%. 그래도 **1/3 이상이 순수 영어**다.
2. "결과 중심"은 참인가? → **부분적으로만.** 실제 지배적 형식은 **Conventional Commits 접두사 + 한국어 본문**이다: `fix(matching): 요건을 더 길게 쓴 게이트도 같은 요건으로 본다 (#274)`. 그리고 하니스 게이트를 그대로 노출한 커밋이 다수다 — `test(aisearch-ac8): RED — V1 defects (… 5 failed, 10 passed)`, `feat(aisearch-ac4): GREEN enforcing gate …`. 이건 '결과 중심'이라기보다 **RED/GREEN 절차 표기**다.
3. 그래도 방향은 맞지 않는가? → 방향은 맞다. 최근 커밋(HEAD~5)은 전부 한국어 결과 서술이다. 하지만 100건 표본에서 43%가 영어라면 "커밋 메시지는 한국어이다"라고 단정할 수 없다.

**정정안**: "커밋 메시지는 **`type(scope):` 접두사(영어) + 한국어 서술** 형식이 우세하다(예: `fix(matching): 요건을 더 길게 쓴 게이트도 같은 요건으로 본다 (#274)`). 최근 100건 중 한글이 포함된 것은 **57%**이고 43%는 영어만 쓴다(Merge 커밋 10건 포함). RED/GREEN 단계를 제목에 그대로 적는 커밋도 많다 — '결과 중심'이라기보다 **하니스 절차 표기 + 한국어 서술 혼용**이 정확하다."

---

# VERDICT

**15개 주장 중 CONFIRMED 5개(C2·C3·C5·C14 + C8 사실부), OVERSTATED 6개(C1·C4·C6·C10·C11·C12·C15 중 7개), FALSE 2개(C7·C13), 혼재 1개(C9 — 5그룹 중 2그룹에 명백한 오분류).** 저장소 규모·CI 제약·verify.sh 동작·자기확장 규칙 같은 **기계로 확인 가능한 사실은 대체로 정확**하나, **강제되지 않는 규칙을 강제되는 것처럼 쓴 것(C13), 커밋 이력으로 알 수 없는 것을 단정한 것(C7), 훅의 발동 조건을 통째로 생략한 것(C11), 파일명만 보고 역할을 붙인 것(C9)** 네 가지는 사장님 보고에서 반드시 정정해야 한다.

## 치명적 오류 목록 (사장님께 보고된 내용 중 사실이 아닌 것)

1. **[C13] "SOT 드리프트 금지 — 같은 PR에 SOT 수정을 동봉해야 머지 가능"** — 이 규칙은 **저장소에 존재하지 않는다**. `docs/harness.md`·`CLAUDE.md` 어디에도 없고, CI(`verify.yml`은 pytest만 돌림)·훅·`make ship` 어디에도 강제 장치가 없다. 유사한 것은 SOT 32 한 건에 붙은 H-NL4 가드뿐. **없는 규칙을 있는 것처럼 보고했다.**

2. **[C7] "최근 커밋 60개에 executor 위임 흔적이 없다"** — 근거 없는 단정. 커밋 트레일러는 `Co-Authored-By: Claude <모델명>`만 남기고 **에이전트 역할을 기록하지 않는다**. 실제로 grep을 돌리면 유일한 hit이 `ThreadPoolExecutor`(파이썬 클래스명)다. 위임 여부는 git 이력으로 판정 불가능하다.

3. **[C9 그룹4] "`dedup.py` = 발송 게이트"** — 틀렸다. `dedup.py`는 프로필 URL 정규화 모듈이고 `embed.py:18`·`dry_run.py:14`(수집·색인 단계)에서만 쓰인다. **`auto_send.py`는 `dedup.py`를 import조차 하지 않는다** — 발송 중복 방지는 원장의 `dedupe_window_days`가 한다.

4. **[C9 그룹3] "`grouping.py` = 후보 채점·매칭"** — 틀렸다. `group_positions(positions) -> tuple[PositionGroup,...]`, `infer_role_family(position)` — **후보가 아니라 채용 포지션(JD)을 직군·연차로 묶는** 모듈이다.

5. **[C11] "훅이 실제로 막는다"** — 발동 조건을 전부 생략해 "항상 막힌다"로 읽힌다. 실제로는 (a) 미커밋 차단은 `.claude/strict-active.json` 마커가 유효할 때만, (b) 증거 없는 완료 차단은 `VH_BUSY_TASK` 환경변수가 있는 **함대 워커 잡 전용**(사장님 대화 세션에는 미적용), (c) 차단은 **1턴 계속 프롬프트**일 뿐 재시도 턴은 무조건 통과, (d) 그 외 모든 모호·예외는 설계상 fail-open이다.

6. **[C12] "ANTHROPIC_API_KEY 제거"** — `claude -p` 호출 3곳 중 **1곳만**(`matching_score_contract.py:377`) 실제로 키를 비운다. `llm_keywords.py:341`·`fleet_worker.py:1038`은 부모 환경을 그대로 상속한다. 이미 되어 있는 것처럼 쓰면 안 되고, 규칙으로 넣으려면 "현재 1/3만 준수"를 함께 적어야 한다. (덤: 이건 실제 미봉 구멍이므로 별도 이슈 가치가 있다.)

7. **[C10] "160개 이상 · `test_<기능>_ac<N>_*.py` 네이밍 관례"** — 실제 **159개**이고, `_ac<N>` 형식은 **10개(6%)**, 그중 9개가 `aisearch` 한 기능 배치 산물이다. 문서에도 규정이 없다. **'관례'가 아니다.**

8. **[C6] "정면 충돌"** — 과장. 전역 규칙서 **자기 안에** 충돌 해소 조항이 있다(`~/.claude/CLAUDE.md:2-8`, "충돌 시 절차(게이트·워크트리)에 한해 Harness 우선"). 남는 건 충돌이 아니라 '위임이 절차에 포함되나' 하는 해석 여지다.

9. **[C4] "검사는 pytest + playwright만 돈다"** — 부정확. CI는 **postgres:16 서비스 컨테이너**를 띄우고 `TEST_DATABASE_URL`을 주입하며 `psycopg[binary]`·`discord.py`도 설치한다(`verify.yml:11-36`). (단 **numpy가 없다는 핵심 결론은 참**이고 `embed.py:6`에 이미 기록돼 있다.)

10. **[C1] "절반이 중복"** — 실측 **34%**(25/73줄). 관대하게 세도 41%. 중복 자체는 실재하므로 방향은 맞지만 수치는 과장.

11. **[C15] "커밋 메시지는 한국어"** — 최근 100건 중 한글 포함 **57%**, 영어만 43%. 실제 형식은 `type(scope):` 영어 접두사 + 한국어 서술 혼용이다.

## 부수 발견 (주장 대상은 아니나 기록)

- **`matching_score_contract.py:379-382`에 CLAUDE.md 주입으로 인한 실제 라이브 장애 기록이 있다** — "프로젝트·전역 CLAUDE.md 와 스킬이 실려서 추출 요청을 작업 지시로 읽고 되묻는다 → JSON 이 없으니 그 후보가 통째로 버려진다(2026-08-01 라이브)". C8("판단을 낭비한다")을 뒷받침하는 저장소 내부의 유일한 실증이다. 새 CLAUDE.md 논거로 쓸 만하다.
- `.claude/skills/` 아래 Anthropic 배포 스킬 번들(`slack-gif-creator`)이 numpy를 import하지만 `verify.sh`가 `pytest tests/`로 경로를 한정하므로 CI에 영향 없다.
