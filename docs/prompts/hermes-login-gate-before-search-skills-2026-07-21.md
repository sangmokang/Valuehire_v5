# Hermes 프롬프트 — url·aisearch·humansearch 스킬 로드 전 login 선행 게이트 (2026-07-21)

> 이 문서는 **Hermes에서 코딩할 때 그대로 붙여 넣는 작업 지시서**다.
> 규율: `docs/sot/30-strict-mode-contract.md`(strict) + `docs/harness.md` 게이트 + CLAUDE.md SOT 불변식.
> 등급: **L2**(운영 경로 코드 변경, 인증 흐름 인접). RED→GREEN + verify + 배선 증명 + V1 적대검증 필수.

---

## 0. 사장님께 한 줄 (쉬운 말)

지금 헤르메스에서 `/url`, `/aisearch`, `/humansearch` 를 부르면 **"로그인 확인하고 시작합니다"라고 말만 하고, 실제로 로그인을 확인하는 코드가 없다.** 이 작업은 그 말을 **코드로 강제**하는 문 하나를 다는 것이다. 로그인 증거가 없으면 검색 스킬이 아예 안 열린다.

---

## 1. 착수 전 확인된 사실 (2026-07-21 실측, 추측 아님)

| # | 사실 | 증거 |
|---|---|---|
| F1 | **login 스킬은 Hermes에 정상 로드돼 있다.** `~/.hermes/skills/login/{SKILL.md, browser-control-contract.json, scripts/}` 존재(2026-07-21 20:43 설치) | `ls ~/.hermes/skills/login/` |
| F2 | 설치본은 레포 정본과 **바이트 동일**(오늘 미커밋 수정분까지 반영됨) | `diff -q skills/login/SKILL.md ~/.hermes/skills/login/SKILL.md` → 동일 |
| F3 | Hermes 시스템 프롬프트 인덱스에 등재됨: 스킬 13개 중 `login/SKILL.md` 포함 | `~/.hermes/.skills_prompt_snapshot.json` → `manifest["login/SKILL.md"]`, `skills[].skill_name == "login"` |
| F4 | `platforms: []`는 **제한 없음(모든 OS 로드)** 의 정상값 — 결함 아님 | `~/.hermes/hermes-agent/tools/skills_tool.py:34-36` "Omit to load on all platforms (default)" |
| F5 | **url·aisearch·humansearch는 Hermes 스킬이 아니다.** `~/.hermes/skills/` 에 없고, valuehire_fleet 플러그인의 **Discord 슬래시 명령**으로만 존재한다 | `ops/hermes-plugin/valuehire_fleet/__init__.py` `_DIRECT_SEARCH_COMMANDS` (미커밋 diff 기준 ~L304) |
| F6 | 현재 인테이크 핸들러는 "login 스킬로 기존 로그인을 확인하고 …" 라고 **문자열로만 약속**한다. 로그인 검증 호출 0건 | 같은 파일 `_make_search_intake_handler` 응답 문자열 |
| F7 | Hermes는 플러그인 `pre_tool_call` 훅에서 **도구 호출 차단**을 지원한다: `{"action":"block","message":"..."}` 첫 번째가 이긴다 | `~/.hermes/hermes-agent/hermes_cli/plugins.py:1678-1723` |
| F8 | 스킬을 실제로 여는 도구 이름은 `skill_view`(목록은 `skills_list`) | `~/.hermes/hermes-agent/tools/skills_tool.py:1504, 1539` |
| F9 | 유효 훅 이름 집합에 `pre_tool_call`·`pre_gateway_dispatch` 포함. 플러그인은 이미 `pre_gateway_dispatch` 하나를 등록 중 | `hermes_cli/plugins.py:128-168`, `valuehire_fleet/__init__.py:312` |
| F10 | **로그인 실행기는 이미 있다 — 새로 만들지 말 것.** `portal_login.run_portal_login_preflight` 가 채널별 로그인을 수행하고 영수증 JSON을 쓴다 | `tools/multi_position_sourcing/portal_login.py:751-805` |
| F11 | 영수증 경로·모양: `artifacts/portal_session_status_latest.json`, `{"kind":"portal_session_preflight","generated_at":…,"ready":bool,"portal_sessions":[…]}` | 같은 파일 `DEFAULT_STATUS_OUTPUT`(L25), `build_portal_session_preflight_payload`(L751-757) |
| F12 | humansearch에는 이미 라이브 fail-closed 프리플라이트가 있다(로그인 리다이렉트·세션충돌 판정). 중복 구현 금지, **재사용/연결**만 한다 | `tools/multi_position_sourcing/humansearch_preflight.py`, `docs/sot/27-humansearch-browsing-preflight.json` |
| F13 | 검증 명령은 `./verify.sh` (내부적으로 `pytest tests/ -q`) | `verify.sh:23` |
| F14 | **실제 흐름은 스킬 로드가 아니라 프롬프트 발행이다.** Discord 명령 → 플러그인 재작성 → `/fleet-run` → `fleet_dispatch` → 잡 큐 → `fleet_worker`가 **"`{skill}` 스킬을 발동해…"라는 프롬프트를 만들어** 해당 머신의 Claude/Codex에게 넘긴다 | `tools/multi_position_sourcing/fleet_worker.py:225-270`, `fleet_dispatch.py:57-165` |
| F15 | 그 프롬프트에는 **login 스킬을 먼저 쓰라는 규칙이 없다.** 규칙 1~19 중 로그인 관련은 3·6·14·19번뿐이고 전부 "알아서 검증해라" 수준의 문장 지시 | `fleet_worker.py:230-268` |
| F16 | **사전 로그인 검증 호출은 0건.** `fleet_worker`는 잡 시작 전에 `portal_login`·`portal_session`·`humansearch_preflight` 중 무엇도 부르지 않는다(heartbeat의 `read_linkedin_login_flag`만 배정 참고용으로 사용) | `fleet_worker.py:29, 1018` (그 외 호출 없음) |
| F17 | **사후 검증은 있으나 자기신고다.** `validate_aisearch_receipt`가 `login_verified is not True`면 실패 처리하지만, 이 값은 **모델이 직접 써 넣는 값**이라 위조 가능하고 검색이 다 끝난 뒤에야 걸린다 | `fleet_worker.py:271-300` |
| F18 | `.claude/skills/{url,aisearch,humansearch}/SKILL.md`에는 이미 "⛔ /login 먼저" 문구가 있다 — **문서(H2) 통제만 존재** | `.claude/skills/url/SKILL.md:52`, `aisearch/SKILL.md:39`, `humansearch/SKILL.md:11` |
| F19 | `install_login_skill`은 `~/.claude/skills/login`, `~/.codex/skills/login`, `~/.hermes/skills/login` 3곳에 설치한다 | `tools/install_login_skill.py:18-20, 974-975` |

**결론(F5+F6+F14~F18):** 문제는 "login 스킬이 로드가 안 됨"이 아니다. 스킬은 3곳 모두 정상 설치돼 있고 문서에도 "/login 먼저"가 적혀 있다. 진짜 구멍은 **검색 경로 어디에도 로그인을 코드로 강제하는 지점이 없다**는 것이다:

- 진입(디스코드) 단계: 로그인 확인한다고 **말만** 한다 (F6)
- 발행(fleet_worker) 단계: 프롬프트에 **login 스킬 지시 자체가 없고**, 사전 검증 호출도 0건 (F15·F16)
- 종료 단계: `login_verified`를 보긴 하지만 **모델 자기신고**라 위조 가능하고 이미 검색이 끝난 뒤다 (F17)

그러므로 작업은 재설치가 아니라 **① 진입 게이트 ② 발행 전 게이트 ③ 프롬프트 규칙 0 ④ 기계 영수증으로 자기신고 대체**, 이 네 곳의 승격(H2 문서 → H3 러너/H4 훅)이다.

### 과거 지시 회수 (Gate 0)

- SOT: `docs/sot/26-portal-login-spec.json`(INV1 자동로그인 의무·INV2·INV6), `docs/sot/27-humansearch-browsing-preflight.json`(fail-closed), `docs/sot/29-fleet-control.md`(함대), `docs/sot/31-fleet-run-reliability.md`.
- 기존 커밋 `fd7e26f docs(skills): aisearch·humansearch·url에 /login 선행 게이트 명시` — **문서(H2)로만 명시된 상태**. 이번 작업은 같은 규칙의 **H3(러너)·H4(훅) 승격**이다(SOT-30 §0, R4 재발 원장 대상).
- 이미 있는 것: `portal_login.py`, `portal_autologin.py`, `portal_session.py`, `portal_live_check.py`, `session_guard.py`, `humansearch_preflight.py`. **새 로그인 구현 금지 — 호출만 한다.**

---

## 2. 목표 (한 문장)

**Hermes에서 url·aisearch·humansearch 경로가 열리기 전에, 기계가 읽을 수 있는 로그인 영수증으로 로그인 성공을 증명하지 못하면 fail-closed로 막고, 막힌 즉시 기존 로그인 실행기를 1회 돌린 뒤 재판정한다.**

비목표(하지 않는다): 새 로그인 로직·새 브라우저 실행·새 창/탭 생성, 캡차/2FA 자동 우회, humansearch 순회 로직 변경, LinkedIn 세션충돌 자동 해결.

---

## 3. 작업 분해표 (R1 — 단위 1개 = 인수기준 1개 = 검증 1개, 단위 관문 R5: 앞 단위 GREEN 전 뒤 단위 착수 금지)

| 단위 | 산출물 | 인수 기준(EARS) | 검증 명령 |
|---|---|---|---|
| U1 | `tools/multi_position_sourcing/login_gate.py` — 순수 판정 함수 | 영수증(dict\|None)·현재시각·요구채널·TTL이 주어지면, 시스템은 `allowed/reason/missing_channels/stale`을 결정적으로 반환한다 | `pytest tests/test_login_gate.py -q` |
| U2 | 영수증 로더 + 실행기 호출 래퍼 (`load_login_receipt`, `ensure_login_or_reason`) | 게이트가 거부되면 시스템은 기존 `portal_login` 실행기를 **정확히 1회** 호출하고 재판정하며, 두 번째 실패는 재시도 없이 사유와 함께 중단한다 | `pytest tests/test_login_gate_runner.py -q` |
| U3 | **[최우선] `fleet_worker` 발행 전 게이트 + 프롬프트 규칙 0** (`fleet_worker.py`) | 워커가 잡 프롬프트를 넘기기 전에 시스템은 **그 머신의** 로그인 영수증으로 판정하고, 통과 시에만 실행하며, 프롬프트 규칙 0에 "login 스킬 먼저 적용"을 넣는다 | `pytest tests/test_fleet_worker*.py -q` |
| U4 | Discord 인테이크 경로 게이트(`_make_search_intake_handler` / 재작성 분기) | 검색 인테이크가 `/fleet-run`을 만들기 전에 시스템은 게이트 상태를 확인하고, 거부면 명령을 발행하지 않으며 **검증하지 않은 "확인하고 시작합니다" 문구를 쓰지 않는다** | `pytest tests/test_hermes_fleet_bridge.py -q` |
| U5 | Hermes `pre_tool_call` 훅 배선(`ops/hermes-plugin/valuehire_fleet/__init__.py`) — 헤르메스 에이전트가 직접 스킬을 열 때의 보조 그물 | `skill_view`가 url·aisearch·humansearch를 열려 할 때 게이트가 거부면 시스템은 `{"action":"block","message":…}`를 반환한다 | `pytest tests/test_hermes_plugin_registration.py -q` |
| U6 | 자기신고 영수증 → 기계 영수증 전환 + SOT 문서 diff | `validate_aisearch_receipt`의 `login_verified`는 모델이 쓴 값이 아니라 `portal_session_status` 영수증과 **대조**해서만 참으로 인정된다 | `./verify.sh` |

diff 예산: 단위당 파일 1~3개 / 50~300줄. 초과하면 멈추고 분할 보고.

---

## 4. 계약 (SDD — 입출력 모양 먼저)

```python
# tools/multi_position_sourcing/login_gate.py
GateSkill = Literal["url", "aisearch", "humansearch"]

REQUIRED_CHANNELS: dict[GateSkill, tuple[str, ...]] = {
    "url":         ("linkedin_rps",),            # RPS 검색 URL 세팅
    "humansearch": ("linkedin_rps", "saramin", "jobkorea"),
    "aisearch":    ("saramin", "jobkorea", "linkedin_rps"),
}

# 채널별 신선도 상한 — 근거: skills/login/SKILL.md §1 상태표
# (사람인·잡코리아 15분, LinkedIn 30분 후 KEEPALIVE 전이)
CHANNEL_TTL_SECONDS = {"saramin": 900, "jobkorea": 900, "linkedin_rps": 1800}

@dataclass(frozen=True)
class LoginGateDecision:
    allowed: bool
    reason: str                       # 기계 판독 코드: OK | NO_RECEIPT | STALE | NOT_READY |
                                      # MISSING_CHANNEL | MALFORMED | CLOCK_SKEW | AUTH_CONFLICT |
                                      # HUMAN_ACTIVE | HUMAN_AUTH | UNKNOWN_INPUT
    missing_channels: tuple[str, ...]
    stale_channels: tuple[str, ...]
    detail: str                       # 사람이 읽는 한국어 한 줄 (비밀값 금지)

def evaluate_login_gate(receipt: object, *, skill: GateSkill, now: float) -> LoginGateDecision: ...
```

불변식: **비밀값(비밀번호·쿠키·토큰) 금지**(SKILL.md 원칙 8). `detail`·block 메시지·로그 어디에도 넣지 않는다.

---

## 5. 입력 영역 표 + 예외 표 (SOT-30 §1-11 ① / R1 ③ — 각 행 = 테스트 1개 이상, 마지막 행은 catch-all)

| # | 입력/상황 | 판정 | 행동 |
|---|---|---|---|
| 1 | 영수증 없음(파일 부재) | `NO_RECEIPT` 거부 | 실행기 1회 호출 후 재판정 |
| 2 | JSON 파싱 실패 / `kind` 불일치 / 스키마 위반 | `MALFORMED` 거부 | 정규화·추정 금지, 즉시 중단 보고 |
| 3 | `ready: false` | `NOT_READY` 거부 | 실행기 1회 호출 후 재판정 |
| 4 | 요구 채널 중 일부만 ready | `MISSING_CHANNEL` 거부 | 부족 채널만 실행기에 전달 |
| 5 | `generated_at`이 채널 TTL 초과 | `STALE` 거부 | 실행기 1회 호출 후 재판정 |
| 6 | `generated_at`이 미래(시계 역행) | `CLOCK_SKEW` 거부 | 신선한 것으로 **간주 금지**(fail-closed) |
| 7 | 영수증에 captcha/2FA/checkpoint 신호 | `HUMAN_AUTH` 거부 | 실행기 재호출 금지. 창 1회 표면화 + 사장님 인계(SOT INV1 예외) |
| 8 | LinkedIn `enterprise-authentication/sessions`·multiple sign-in | `AUTH_CONFLICT` 거부(terminal) | 자동 로그인·Continue 클릭·재시도 **0회**, 영구 중단 (SKILL.md §0-7) |
| 9 | 사장님이 3사 포털 화면 조작 중 | `HUMAN_ACTIVE` 보류 | 무조작 대기, **60초 무이상 시 자동 재개**(CLAUDE.md SOT2/SOT29 INV9) |
| 10 | 요구 채널 밖 스킬 이름(오탈자·미지의 값) | `UNKNOWN_INPUT` 거부 | 기본 허용 금지 |
| 11 | 같은 사용자·채널에서 검색 2건 동시 진입 | 거부 | 기존 lease/idempotency 재사용, 새 락 신설 금지 |
| 12 | 실행 기기가 헤르메스 호스트와 다름(원격 함대) | 거부 | **실행 호스트에서** 재판정(U5) — 원격 영수증을 로컬 판정으로 대체 금지 |
| 13 | macOS 아님 / 위임 없는 WinPC | `HUMAN_ACTIVE` 거부 | SKILL.md 서문대로 중단, 안전성 주장 금지 |
| 14 | **그 외 전부** | 거부 | 명시적 중단 + 이 표 갱신안 보고 (임의 판단 금지) |

---

## 6. 배선 지점 (정확한 위치와 방법)

1. **훅 등록** — `ops/hermes-plugin/valuehire_fleet/__init__.py` `register(ctx)` 안, 기존 `ctx.register_hook("pre_gateway_dispatch", …)` 옆에
   `ctx.register_hook("pre_tool_call", _login_gate_before_search_skill)`.
2. **훅 시그니처** — `def _login_gate_before_search_skill(tool_name="", args=None, **_kw) -> dict | None`.
   - `tool_name not in {"skill_view"}` → `None`(관여 안 함).
   - `args`에서 스킬 이름 추출 후 `valuehire_fleet:` 등 네임스페이스 접두어 제거 → `{url, aisearch, humansearch}` 아니면 `None`.
   - 게이트 거부 → `{"action": "block", "message": "<한국어 사유 + 다음에 할 정확한 명령 1줄>"}`.
   - **예외가 나면 통과시키지 않는다**: `except Exception` → block(fail-closed). 반환 계약 근거: `hermes_cli/plugins.py:1692-1721`.
3. **인테이크 경로** — `_make_search_intake_handler`가 `/fleet-run` 문자열을 만들기 **전에** 게이트 판정. 거부면 명령을 발행하지 않고 사유를 답한다(지금처럼 "확인하겠습니다"라고 **말만 하는 문구 삭제** — 말과 코드가 어긋나면 그 자체가 위반).
4. **실행기 호출(R3 러너 소유)** — 게이트가 실행 가능 사유(1·3·4·5)로 거부하면:
   `PYTHONPATH=. python3 -m tools.multi_position_sourcing.portal_login --channels <부족채널> --output artifacts/portal_session_status_latest.json`
   1회 실행 → 영수증 재판독 → 재판정. **2회차 재시도 금지**(봇 행동 금지, CLAUDE.md SOT2).
5. **워커(가장 중요, F14~F17)** — `fleet_worker`가 잡 프롬프트를 넘기기 직전:
   - 같은 `evaluate_login_gate`를 **실행 호스트에서** 호출(헤르메스 쪽 판정으로 대체 금지).
   - 프롬프트 규칙에 **규칙 0** 추가: `"0. 무엇보다 먼저 login 스킬(skills/login/SKILL.md)을 적용해 기존 CDP 브라우저·기존 탭만 재사용하고(새 창 0·새 탭 0), 사이트별 로그인 마커로 증명한 뒤에만 {skill}을 시작할 것."`
   - `validate_aisearch_receipt`의 `login_verified`는 모델 자기신고를 그대로 믿지 말고 영수증 파일과 대조한다.

---

## 7. 게이트 절차 (harness / SOT-19)

0. `git status` 깨끗한 상태에서 시작. **⚠️ 현재 메인 작업트리에 로그인·플러그인 관련 미커밋 변경 10개 파일이 있다** — 착수 전 이 변경들의 처리(커밋 or stash)를 먼저 정하고, 그 위에 얹지 않는다.
1. 워크트리: `npm run wt -- <issue>-hermes-login-gate` (임의 `git worktree add` 금지).
2. **RED 먼저**: U1 테스트를 표 14행 그대로 작성 → 올바른 이유로 실패하는 것 확인 → 커밋.
3. GREEN: 최소 변경.
4. 검증: `./verify.sh` 출력 숫자 그대로 인용 + **라이브 1건**(실제 Hermes에서 `/aisearch` → 로그인 없는 상태 block 메시지 캡처, 로그인 후 통과 캡처).
5. 배선 증명: Hermes 프로세스 로그(`HERMES_PLUGINS_DEBUG=1`)에 `registered hook: pre_tool_call` 라인 + 실제 block 발생 라인. **"테스트가 import해서 통과"는 배선 증명이 아니다.**
6. V1 적대검증: `/codex:adversarial-review --fresh` (fresh·read-only). 정조준 지시: ① 표 14행 밖의 현실 입력이 있는가 ② block을 우회하는 다른 스킬 로드 경로(`skills_list` 후 파일 직접 read, 다른 도구명, 플러그인 스킬 네임스페이스)가 남아 있는가 ③ 영수증 신선도만 보고 실제 세션 만료를 놓치는가 ④ 실패 시 조용히 통과(fail-open)하는 분기가 있는가.
7. `docs/sot/26-portal-login-spec.json` 또는 신규 SOT 항목에 게이트를 명문화하고 같은 PR에 diff 동봉.

---

## 8. 완료 정의 (전부 ✅ 아니면 "진행 중")

- [ ] 로그인 영수증 없는 상태에서 Hermes `/aisearch` → **차단 메시지**가 실제로 뜬다(캡처).
- [ ] 로그인 후 같은 명령 → 통과하고 검색이 시작된다(캡처).
- [ ] 표 14행 전부 테스트 존재, `./verify.sh` exit 0 (숫자 그대로 인용).
- [ ] 새 창 0개·새 탭 0개·브라우저 종료 0건(SKILL.md §10 체크리스트).
- [ ] 비밀값이 메시지·로그·아티팩트 어디에도 없다.
- [ ] V1 판정 본문 확보(경로 포함).
- [ ] 말(응답 문구)과 코드(실제 검증)가 일치한다 — 검증 없는 "확인했습니다" 문구 0건.
