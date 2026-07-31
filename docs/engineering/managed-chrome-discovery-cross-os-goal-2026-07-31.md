# goal — humansearch 관리 브라우저 발견을 macOS·Windows에서 코드가 직접 판정

> 작성 2026-07-31 · 모드 `code-change` · 위험등급 **L3** (로그인/인증 판정 경로 · 잘못되면 개인 Chrome 오조작 — 비가역)
> 워크트리 `../Valuehire_v5-managed-chrome-discovery-cross-os` · 브랜치 `task/managed-chrome-discovery-cross-os`
> 기준 커밋 `b254a80` (main). 직전 관련 변경 `3590cd6` = PR#252 "reuse live authenticated LinkedIn Talent target".

---

## 0. 읽은 SOT / 과거 지시 회수

| 문서 | 이 작업과의 관계 |
|---|---|
| `CLAUDE.md` (레포 최상위) | SOT 불변식 1(3사 로그인은 자동화가 한다, 2FA·캡차만 사람) · 2(R4 사장님 양보) · 5(두 번 깐다) |
| `docs/sot/26-portal-login-spec.json` | INV1/INV2/INV5/INV6 — 관리 브라우저 발견 알고리즘, 단일탭 HTTP `/json`, 창 닫기 금지 |
| `docs/sot/27-humansearch-browsing-preflight.json` | humansearch 사전 게이트(점유·캡차·로그인) |
| `docs/sot/29-fleet-control.md` / `.json` | 3대 머신(VH-SM-000/001/002) 계정↔머신 바인딩, INV9 개입·재개 |
| `docs/sot/30-strict-mode-contract.md` | 이 작업의 실행 계약(L3 = G→V1→V2 + verdict.json) |
| `docs/harness.md` | 게이트 0~6 |

### 과거 지시 회수 (중복 구현 금지)

이미 **구현돼 있는 것**(다시 만들지 않는다):

- `tools/multi_position_sourcing/portal_worker.py:110` `discover_local_chrome_cdp_endpoints` — macOS `ps ax` 기반 루트 Chrome 발견 + `.valuehire` 프로필 경계 + 채널 토큰 검사.
- `tools/multi_position_sourcing/portal_worker.py:187` `_find_unique_live_channel_endpoint` — 후보 endpoint 중 공식 화면이 있는 **유일한** 것만 채택.
- `tools/multi_position_sourcing/portal_worker.py:227` `resolve_managed_channel_cdp_endpoint` — `scripts/portal_browsers.sh cdp <name>` → 실패 시 발견 폴백.
- `tools/multi_position_sourcing/portal_worker.py:303` `url_matches_channel_surface` — HTTPS + 정확한 host 경계 + 공식 path (룩얼라이크 차단).
- `tools/multi_position_sourcing/session_guard.py:286` `resolve_managed_browser_process` — macOS `ps ax -o pid=,command=` 루트 프로세스 유일성 + `lsof` listener 교차확인.
- `tools/multi_position_sourcing/session_guard.py:413` `resolve_existing_target` — 정확한 target 1개 결합, 생성·첫탭 폴백 없음.
- `tools/multi_position_sourcing/portal_selfservice_login.py:89` `decide_login_step` — `already_authenticated` / `security_challenge` / `session_conflict` / `fill_credentials`; `perform_autologin`은 이미 로그인 시 `{"state": "AUTHENTICATED", "mutations": 0}`.
- `tools/multi_position_sourcing/humansearch_cdp_run.py:234` `resolve_exact_recruiter_target` — `resolve_existing_target`를 소비하는 humansearch 실제 준비 경로.
- `tools/multi_position_sourcing/search_machine.py` — VH-SM-002(Windows) 포트 9423/9424/9425 + `%LOCALAPPDATA%\Valuehire\portal_profiles\sm002\<채널>` 등록부.

과거 브랜치 `origin/task/winpc-local-ai-search`에 있는 **재이식 대상 순수 함수**(전체 merge/cherry-pick 금지, 필요한 것만):

- `session_guard.py:291` `_windows_command_line_argv` — `Win32_Process.CommandLine` → argv (shell 미사용).
- `session_guard.py:307` `_windows_chrome_options` — argv → `--flag=value` 다중값 맵.
- `session_guard.py:333` `list_windows_managed_browser_processes` — 고정 PowerShell 인자 배열 + `ConvertTo-Json` + 루트/포트/프로필 검사.
- `resolve_managed_browser_process`의 `system_name` 분기.

**재이식하지 않는 것**: 같은 브랜치의 `resolve_managed_channel_cdp_endpoint` Windows 분기는 **설정 포트를 그대로 믿고** `/json/version`만 확인한다 — 본 목표의 "설정 포트는 죽고 다른 실제 포트가 살아 있음" 행을 만족하지 못하므로 채택하지 않는다. `winpc_local_aisearch.py` / `winpc_portal_browser.py`(브라우저 실행·전면화)는 본 범위 밖.

`task/three-machine-live-verification`은 기준 브랜치로 쓰지 않는다(실기기 사례만 참조).

### 재발 장부 인용 (`docs/prompts/strict-decompose-tdd-ladder-prompt-2026-07-19.md:5`)

> 반복 실패 사례(원장 초기 6건): ① 스펙 내 사항 중간 질문 남발 ② 명령/SOT 위반 **③ 로그인 지시 미이행** ④ 로그인창 임의 닫기 **⑤ 로그인창 못 찾고 배회** **⑥ RPS 검색창에 불린 쿼리 오입력**.

이 작업이 그 세 건에 거는 통제:

| 재발 항목 | 이번 통제 |
|---|---|
| ③ 로그인 지시 미이행 | 이미 로그인된 화면은 코드가 `AUTHENTICATED`로 확정해 모델이 "로그인 안 됐다"고 재해석할 여지를 없앤다. 상태 코드→고정 문구 표를 코드에 둔다. |
| ⑤ 로그인창 못 찾고 배회 | Windows에서 `ps` 실패로 후보가 0개가 되던 경로를 OS별 조회기로 갈라, 발견 실패는 배회가 아니라 `NO_MANAGED_BROWSER` 고정 코드로 즉시 중단. 포트 무차별 탐색 금지. |
| ⑥ 잘못된 검색창 오입력 | 등록 프로필 경계 + 루트/실제포트 유일성 + 공식 Talent 화면 유일성 3중 증명 전에는 검색 단계로 넘기지 않는다(개인 Chrome 오조작 원천 차단). |

---

## 1. 현재 상태 (추측 없이 file:line)

| 사실 | 근거 |
|---|---|
| 관리 브라우저 발견이 Unix `ps ax`에만 의존 | `portal_worker.py:123-129` (`runner(["ps","ax","-o","command="] ...)`) |
| 프로필이 POSIX 절대경로여야만 통과 → `C:\...` 거부 | `portal_worker.py:162-168` (`profile.replace("\\","/")` 후 `not profile.startswith("/")` 이면 skip) |
| 셸 실행기 실패가 Windows 탐색으로 이어지지 않음 | `portal_worker.py:252-253` — `portal_browsers.sh` 실행이 `OSError`면 **즉시** `LookupError`. 발견 폴백(`254-269`)은 `returncode != 0`일 때만 탄다. Windows에는 `.sh` 실행기가 없어 `OSError` → 후보 0개. |
| 프로세스 결합도 Unix `ps` 전용 | `session_guard.py:305-311`, 다중 매치 해소는 `lsof` (`364-377`) — 둘 다 Windows 부재 |
| 두 함수 모두 `system_name`/`env` 주입구 없음 | `portal_worker.py:110-114`, `session_guard.py:286-291` 시그니처 |
| Windows 기기 등록부는 이미 존재 | `search_machine.py:74-86` (VH-SM-002, 9423/9424/9425, `%LOCALAPPDATA%\Valuehire\portal_profiles\sm002\<채널>`) |

**근본 원인**: 발견 계층이 "OS 중립 계약"이 아니라 "Unix 도구 호출"로 구현돼 있고, 그 실행 실패가 *조회 실패*가 아니라 *후보 없음*으로 흡수된다. 그래서 WinPC에서 `chrome.exe`가 살아 있어도 후보 0개가 되고, 모델이 그 공백을 추측으로 메우게 된다.

---

## 2. 계약 (입출력 모양 먼저 — SDD)

```python
# portal_worker.py
def discover_local_chrome_cdp_endpoints(
    *, channel: str | None = None,
    runner=subprocess.run,
    system_name: str | None = None,     # None → platform.system()
    env: Mapping[str, str] | None = None,  # None → os.environ
) -> list[str]:
    """살아 있는 루트 Chrome이 선언한 로컬 디버깅 endpoint 목록(중복 제거, 순서 보존).
    조회 자체가 불가능/실패면 ManagedBrowserDiscoveryError(고정 코드)."""

def resolve_managed_channel_cdp_endpoint(
    channel: str, *, runner=subprocess.run,
    system_name: str | None = None, env: Mapping[str, str] | None = None,
    endpoint_discoverer=None, list_tabs=None,
) -> str:  # "http://127.0.0.1:<port>" 정확히 1개

# session_guard.py
def resolve_managed_browser_process(
    site, endpoint, *, runner=subprocess.run, system_name: str | None = None,
) -> ManagedBrowserProcess  # (browser_pid, profile_path)
```

상태 코드 → 사용자 고정 문구(코드 상수, 모델이 재작성 못 함):

| 코드 | 고정 한국어 문구 |
|---|---|
| `AUTHENTICATED` | 이미 로그인된 전용 크롬을 그대로 씁니다. 조작 없이 검색으로 넘어갑니다. |
| `NO_MANAGED_BROWSER` | 이 컴퓨터에서 밸류하이어 전용 크롬을 찾지 못했습니다. 검색을 시작하지 않습니다. |
| `AMBIGUOUS_MANAGED_BROWSER` | 전용 크롬이 두 개 이상이라 어느 것도 고르지 않았습니다. |
| `NO_OFFICIAL_TARGET` | 전용 크롬에 공식 링크드인 탤런트 화면이 없습니다. |
| `AMBIGUOUS_OFFICIAL_TARGET` | 공식 화면이 여러 브라우저에 있어 선택하지 않았습니다. |
| `HUMAN_AUTH` | 본인확인·보안 화면입니다. 사장님이 직접 처리해 주셔야 합니다. 검색은 하지 않았습니다. |
| `UNSUPPORTED_OS` | 지원하지 않는 컴퓨터 환경입니다. |
| `BROWSER_QUERY_FAILED` | 브라우저 조회 명령이 실패했습니다. 추측하지 않고 멈춥니다. |

---

## 3. 인수 기준 (EARS, 단일)

**WHEN** macOS 또는 native Windows에서 humansearch 준비 경로가 실행되고, 그 PC에 등록된 채널 프로필로 뜬 ValueHire 전용 Chrome이 **정확히 하나** 살아 있으며 그 브라우저에 공식 LinkedIn Talent 화면이 **정확히 하나** 있고 이미 로그인돼 있으면,
**THE SYSTEM SHALL** 그 브라우저·창·탭을 그대로 재사용해(페이지 이동 0 · 자격증명 입력 0 · 제출 0 · 탭/창/브라우저 종료 0) `AUTHENTICATED`를 반환하고 humansearch 실제 준비 경로가 이를 받아 다음 단계로 진행한다.
**AND** 위 3중 유일성(등록 프로필 경계 / 루트·실제 포트 / 공식 화면) 중 하나라도 증명되지 않거나 보안 확인·다중 로그인 충돌이면 검색 실행 0회로 §2 표의 고정 상태 코드로 중단한다.

- 검증 명령: `.venv/bin/python -m pytest tests/test_managed_chrome_discovery_cross_os.py -q` 및 `./verify.sh`
- counter-AC: 개인 Chrome 프로필(등록부 밖)만 살아 있고 그 안에 Talent 탭이 있어도 결과는 `NO_MANAGED_BROWSER`이며 검색 0회여야 한다.

---

## 4. 입력 영역 표 (결정성 규율 ①) — 각 행 = 검사 ≥1

| # | 입력 상태 | 처리 |
|---|---|---|
| 1 | macOS · 전용 Chrome 1개 | 기존 `ps` 경로 그대로(회귀 유지) |
| 2 | Windows · 전용 `chrome.exe` 1개 | Windows 조회기(PowerShell `Get-CimInstance`)로 처리 |
| 3 | 지원하지 않는 OS(Linux 등) | `UNSUPPORTED_OS` 고정 중단 |
| 4 | 해당 프로세스 0개 | `NO_MANAGED_BROWSER` |
| 5 | 루트 1 + 자식 다수(`--type=renderer/gpu-process`) | 자식 제외, 루트만 채택 |
| 6 | 루트 프로세스 2개 이상 | `AMBIGUOUS_MANAGED_BROWSER` |
| 7 | `--remote-debugging-port` 누락/중복/범위 밖(0·65536·비ASCII) | 그 프로세스 거부(명시적) |
| 8 | `--user-data-dir` 누락/상대경로/제어문자 | 그 프로세스 거부(명시적) |
| 9 | 공백 포함 인용 Windows 경로 `"C:\Users\a b\...\linkedin"` | 정확히 1개 값으로 해석 |
| 10 | 개인 Chrome 프로필(`%LOCALAPPDATA%\Google\...`) | 제외 |
| 10a | 등록값과 이름만 비슷한 폴더(`Valuehire2`, `...\saramin\linkedin-decoy`, `Valuehire` 2회 중첩) | 제외 — 등록부 값과 **정확일치**만 인정 (V1-F1) |
| 10b | 원격/UNC 경로(`\\server\share\...`) | 제외 — 이 컴퓨터의 등록 프로필이 아님 (V1-F1) |
| 10c | `%LOCALAPPDATA%` 미설정 | 등록 프로필을 확정할 수 없으므로 후보 0개(fail-closed) |
| 11 | ValueHire 경로지만 다른 채널 프로필(saramin인데 linkedin 요청) | 제외 |
| 12 | 설정 포트는 죽고 실제 포트가 다름 | 실제 포트를 발견·검증 후 사용 |
| 13 | 디버깅 주소가 로컬이 아님(`http://10.0.0.5:9425`, 자격 포함, path/query 있음) | 거부 |
| 14 | 공식 Talent 화면 0개 | `NO_OFFICIAL_TARGET` |
| 15 | 관리 루트가 2개 이상(화면이 한쪽에만 있어도) | `AMBIGUOUS_MANAGED_BROWSER` — 유일성은 화면 검사보다 먼저 확정 (V1-F2) |
| 15a | 한 브라우저 안에 공식 화면이 여러 개이고 target id 미지정 | `AMBIGUOUS_OFFICIAL_TARGET` |
| 16 | 룩얼라이크(`linkedin.com.evil.io`) 또는 일반 LinkedIn(`/feed`) | 거부 |
| 17 | 이미 로그인된 Talent 화면 | `AUTHENTICATED` · 조작 0회 |
| 18 | 캡차·2FA·checkpoint | `HUMAN_AUTH` · 검색 0회 |
| 19 | 다중 로그인 충돌 | `HUMAN_AUTH` · 검색 0회 |
| 20 | 조회 명령 실패(비-0 종료) 또는 JSON 파손 | `BROWSER_QUERY_FAILED` 고정 중단(빈 목록으로 숨기지 않음) |
| 21 | **그 외 전부** | 추측 금지 — 명시적 중단(catch-all) |

## 4.1 결정 목록 (결정성 규율 ②)

| 결정 | 확정값 | 근거 |
|---|---|---|
| Windows 프로필 동일성 기준 | `ntpath.normcase(ntpath.normpath(...))` — 대소문자·구분자 정규화 | Windows 파일계 규칙 |
| 등록 프로필 경계 | `%LOCALAPPDATA%\Valuehire\` 하위 + 채널 토큰 일치 | `search_machine.py:83-85` |
| 포트 유효 범위 | 1~65535, ASCII 숫자만 | 기존 `portal_worker.py:84-86` 규칙 유지 |
| 조회 실패 vs 후보 0 | **구분한다** — 실패는 `BROWSER_QUERY_FAILED`, 진짜 0개만 `NO_MANAGED_BROWSER` | 표 20행 |
| macOS 동작 | 변경 없음(회귀 0) | 기존 18개 검사 유지 |

## 4.2 예외 케이스 표 (R1)

표 4의 3·4·6·7·8·10·11·13·14·15·16·18·19·20·21행이 곧 "명시적 중단" 행이다. 표에 없는 상황이 나오면 임의 판단 없이 중단하고 표를 갱신한 뒤 재개한다.

---

## 5. 구현 제약 (지킬 것)

- Windows에서 `ps`·Bash·`portal_browsers.sh`를 **실행하지 않는다**.
- Windows 조회는 **고정 인자 배열 + `shell=False`**. 사용자 입력을 PowerShell 문자열에 삽입하지 않는다.
- `chrome.exe` 루트만, `--type` 자식 제외. 포트·프로필 플래그는 각각 정확히 1개.
- 9222~9999 무차별 스캔 금지. 첫 탭·첫 열린 포트 같은 임의 선택 금지.
- 브라우저·창·탭을 새로 열지 않고, **절대 닫지 않는다**(연결 해제만).
- 이미 로그인된 화면에서 이동·입력·제출 0회.
- 기존 로그인 제출/캡차/다중로그인 우선순위 약화 금지. 예외를 빈 목록으로 숨기지 않는다.
- 검사 삭제·skip·단언 약화 금지.
- 코드에 특정 사용자명·특정 저장소 절대경로·고정 실제 포트 하드코딩 금지.
- 자동 업데이트·타 PC 배포는 **비범위**.

## 5.1 크기 제한

구현 파일 ≤5, 구현 변경 ≤300줄. 초과 시 "기존 로그인 창 발견 + 실제 경로 연결"까지만 완결하고 분할 보고.

---

## 6. 게이트 계획

0 red-ledger(통과, 열린 RED는 사장님 우선순위로 PARKED) → 1 본 문서 → 2 RED 테스트 커밋 → 3 최소 구현 → 4 `./verify.sh` exit 0 + 표 21행 검사 + 배선 증명 → 5 push→PR→CI→merge → 6 정리.

## 7. 적대검증 정조준 (V1/V2가 공격할 곳)

1. 개인 Chrome이 등록 프로필과 **접두사만 같은** 경로(`...\Valuehire2\...`)일 때 뚫리는가?
2. Windows argv 파싱이 공백/따옴표/이스케이프 조합에서 프로필을 잘라먹는가?
3. `--type` 없이 뜨는 자식이나, `--remote-debugging-port`를 값 분리형(`--flag value`)으로 준 경우?
4. 조회 실패를 어딘가에서 여전히 빈 목록으로 흡수하는 경로가 남았는가?
5. `resolve_existing_target`가 Windows 분기를 실제로 호출하는가(고아 코드 아닌가)?
6. 표·결정 자체의 결함 — 표에 없는 현실 입력(WSL, Chrome Beta, 32/64비트 경로)?

## 8. 비범위

- Windows에서 브라우저를 **실행**하거나 전면화하는 기능
- 다른 PC로의 코드 자동 배포/업데이트
- 검색 실행·채점·등록 로직 변경
- macOS 동작 변경

## 9. 롤백 (L3)

단일 PR revert로 원복. 새 코드는 기존 macOS 경로를 감싸지 않고 OS 분기만 추가하므로, revert 시 `3590cd6` 시점 동작으로 정확히 되돌아간다. 영향 반경: humansearch 준비 경로(`humansearch_cdp_run.resolve_exact_recruiter_target`) 및 `session_guard.resolve_existing_target` 호출자 전부 — 라이브 발송·등록 경로는 건드리지 않는다.

---

## 적대 검증 로그

### G (생성자 자체 반증) — 2026-07-31

| # | 시도 | 결과 | 조치 |
|---|---|---|---|
| G1 | 공백 있는 인용 Windows 경로 `--user-data-dir="C:\Users\Kang Sang Mo\..."` | **뚫림** — `shlex.split(posix=False)`가 토큰 중간 따옴표를 무시하고 공백에서 잘라 프로필이 3조각이 됨 → 후보 0개 | `parse_windows_command_line`을 `CommandLineToArgvW` 규칙 토크나이저로 교체(`windows_chrome.py`). 과거 브랜치 `origin/task/winpc-local-ai-search`의 `shlex` 구현을 채택하지 않은 이유 |
| G2 | 이름만 같은 폴더 `D:\temp\Valuehire\linkedin`, `C:\Valuehire\linkedin` | **뚫림** — `valuehire` 조각만 확인해 `%LOCALAPPDATA%` 밖도 통과 | `is_registered_windows_profile`에 `local_app_data` 결합 + 미설정 시 `appdata\local\valuehire` 조각 순서 강제. `env` 인자를 실제로 사용하도록 배선(그전엔 받기만 하고 무시) |
| G3 | CI(ubuntu-latest)에서 전체 검사 | **깨짐** — macOS 프로세스 목록을 흉내내는 기존 검사 7건이 `UNSUPPORTED_OS`로 실패 | 그 7건에 시뮬레이션 대상 OS(`system_name="Darwin"`)를 명시. 단언·케이스 삭제 0건 |
| G4 | 따옴표 앞 역슬래시 `--user-data-dir="...\linkedin\"` | 못 뚫음 — 값에 `"`가 남아 채널 토큰 불일치로 fail-closed | 조치 불요 |
| G5 | 따옴표 없는 공백 경로 `--user-data-dir=C:\Users\Kang Sang Mo\...` | 못 뚫음 — `C:\Users\Kang`으로 잘려 등록 경계 불일치로 fail-closed(오탐 아님) | 조치 불요 |
| G6 | 탭 구분·빈 인자·값 분리형 `--user-data-dir C:\...` | 못 뚫음 — 모두 정확히 1개 값으로 해석 | 조치 불요 |
| G7 | `\\?\C:\...` UNC 접두, 대문자, 후행 공백, `linkedinfake`, `..` 탈출, `Google\Valuehire` | 못 뚫음 — `linkedinfake`·`..`·`Google\Valuehire`·루트 `Valuehire`는 거부, 동일 폴더의 다른 표기만 허용 | 조치 불요 |
| G8 | 고아 코드 여부 | 배선 확인 — `humansearch_cdp_run.main()` (`humansearch_cdp_run.py:742`, `target_resolver=None` 기본값) → `resolve_exact_recruiter_target:242` → `session_guard.resolve_existing_target:441/455` → `portal_worker.resolve_managed_channel_cdp_endpoint` + `session_guard.resolve_managed_browser_process` → OS 분기 | 조치 불요 |
| G9 | 변이 검사 — `if "type" in options: continue`(자식 제외) 제거 | 검사가 즉시 잡음(`test_binds_endpoint_to_single_windows_root_process` 실패) → 복원 후 32 passed | 조치 불요 |

실행 증거:
- `.venv/bin/python -m pytest tests/test_managed_chrome_discovery_cross_os.py -q` → **32 passed, 22 subtests passed**
- `./verify.sh` (macOS) → **3293 passed, 4 xfailed, 127 subtests passed**, `verify: pytest exit=0`
- `platform.system` 을 `Linux`로 강제한 전체 실행(CI 환경 재현) → **3293 passed, 4 xfailed, 127 subtests passed**
- `make strict-exit-gate` → `PASS — 미커밋 잔존 0 · 마커 상태 일치`

### V1 (Codex 독립 적대검증) — 2026-07-31, **VERDICT: FAIL** → 전건 수정 후 재검증

판정 본문 출처: Codex 세션 `~/.codex/sessions/2026/07/31/rollout-2026-07-31T22-15-12-019fb850-83a1-71c3-885a-1a69244f4621.jsonl`
(codex-rescue 래퍼가 최종 메시지를 `Done.`으로만 반환해 무효 — 세션 롤아웃에서 본문을 회수했다. 래퍼 결함은 별도 과제)

Codex 실행 증거(읽기 전용 샌드박스):
- `pytest tests/test_managed_chrome_discovery_cross_os.py -q -s -p no:cacheprovider` → `32 passed, 22 subtests passed`, exit 0
- `pytest tests/test_channel_endpoint_marker_verify.py tests/test_login_session_runner.py tests/test_managed_chrome_discovery_cross_os.py -q -s` → `122 passed, 25 subtests passed`, exit 0
- 명령행 교차검사 `cases=781 mismatches=0`
- 검사 변경 감사 `darwin_additions=7, deleted_test_defs=0, deleted_assert_lines=0, deleted_skip_lines=0` (테스트 약화 없음 확인)
- 전체 실행은 읽기 전용 샌드박스 제약으로 `191 failed / 304 errors` — Codex 스스로 "제품 회귀 숫자로 판정하지 않았다"고 명시. 채택하지 않음

| # | Codex 지적 | 내 재현 | 조치 |
|---|---|---|---|
| V1-F1 (심각) | 등록 경계 우회 — `...\sm002\saramin\linkedin-decoy`, 원격 UNC, `Valuehire` 2회 경로가 후보로 채택 | **재현됨**(3건 모두 `True`) | 조각 이름 추정을 폐기하고 **기기 등록부(`search_machine.SEARCH_MACHINES`)의 값과 정규화 후 정확일치**로 교체. `%LOCALAPPDATA%`는 실제 환경변수로만 펼치고, 없으면 등록 프로필을 하나도 확정하지 않아 fail-closed. UNC(`\\`) 명시 거부 |
| V1-F2 (심각) | 관리 루트 2개인데 한쪽에만 Talent 화면이 있으면 그쪽을 선택 | **재현됨**(`http://127.0.0.1:9425` 선택) | 루트 유일성을 **공식 화면 검사보다 먼저** 확정. 2개 이상이면 `AMBIGUOUS_MANAGED_BROWSER` |
| V1-F3 (심각) | 인증 전 배지 추가로 조작 0회 위반 | **재현 안 됨** — 인증 경로의 attach는 모두 `badge=False`(`session_guard.py:1511` 기본값 False, `humansearch_cdp_run.py:747` 명시 False). `raw_cdp.attach`의 기본 `badge=True`는 이 경로에서 쓰이지 않음. 이동은 `assert_not_blocked_or_abort` 이후 검색 단계이므로 계약 범위 밖 | 조치 없음(기록 보존). `raw_cdp.attach` 기본값이 잠재 함정인 점은 별도 과제 |
| V1-F4 (높음) | 후보0·화면0·후보2·조회예외가 전부 `code=None` 일반 오류로 합쳐짐 | **재현됨**(`LookupError code=None`) | `NO_MANAGED_BROWSER`/`AMBIGUOUS_MANAGED_BROWSER`/`NO_OFFICIAL_TARGET`/`AMBIGUOUS_OFFICIAL_TARGET`를 각 발생 지점에 배선. `resolve_existing_target`의 target 수 불일치도 고정 코드로 |
| V1-F5 (높음) | `[1,2,3]` 같은 구조 파손 JSON이 빈 목록으로 흡수 | **재현됨**(`[]` 반환) | 한 행이라도 프로세스 모양이 아니면 `BROWSER_QUERY_FAILED` |
| V1-F6 (중간) | `--type` 없는 자식이 루트로 채택 | 이론상 성립 | 조회에 `ParentProcessId` 추가 — 부모가 조회된 chrome.exe면 제외 |
| V1-F7 (중간) | 작은따옴표를 벗겨 다른 경로를 등록 경로로 판정 | **재현됨**(`True`) | Windows에서 의미 있는 `"` 만 벗긴다 |
| V1-F8 (중간) | 표 결함 — Chromium은 허용목록에 있으나 조회에서 제외, Beta/Canary 구분 불가, 8.3 단축명 | 성립 | 허용목록을 조회와 동일하게 `chrome.exe` 하나로 축소. Beta/Canary/portable은 **등록 프로필 정확일치**로 걸러지므로 실행 파일 구분에 의존하지 않음 |

수정 후 재검증:
- `pytest tests/test_managed_chrome_discovery_cross_os.py -q` → **41 passed, 22 subtests passed**
- `./verify.sh` (macOS) → **3302 passed, 4 xfailed, 127 subtests passed**, `verify: pytest exit=0`
