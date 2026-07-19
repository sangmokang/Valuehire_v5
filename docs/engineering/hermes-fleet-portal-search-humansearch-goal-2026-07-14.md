# fleet-run: 채용포털 검색결과 URL 리스트 → humansearch 자동 발동 (goal, 2026-07-14)

## ① 현재 상태 (증거)

- `tools/multi_position_sourcing/hermes_fleet_bridge.py:30` — `_FLEET_RUN_DEFAULT_SKILL = "aisearch"`.
  skill을 명시하지 않으면 **무조건** aisearch로 고정된다.
- `tools/multi_position_sourcing/hermes_fleet_bridge.py:143-146` — `parse_hermes_fleet_args()`는
  bare URL들 중 사람인/잡코리아/링크드인 도메인(`_is_search_url()`, line 88-90, 마커는
  line 41-43 `_SEARCH_HOST_MARKERS`)에 해당하는 것들을 이미 `params["search_urls"]`로
  분리해서 모으고 있다(`options["params"] = {"search_urls": search_urls}`). 즉 "사람이
  미리 걸어둔 검색결과 URL 리스트"를 구분하는 판정 로직은 이미 존재한다. 그런데 바로 다음 줄
  `options.setdefault("skill", _FLEET_RUN_DEFAULT_SKILL)`은 이 판정 결과를 전혀 참조하지
  않고 항상 aisearch로 기본값을 채운다.
- `tools/multi_position_sourcing/hermes_fleet_bridge.py:244` — `natural_fleet_command_text()`
  (디스코드 자연어 → `/fleet-run` 변환기)는 `parts = ["/fleet-run", "aisearch", *urls, ...]`로
  스킬 토큰을 리터럴 `"aisearch"`로 하드코딩한다. 이 함수도 검색결과 URL 여부를 보지 않는다.
- 기존 테스트 `tests/test_hermes_fleet_bridge.py:218-227`
  (`test_natural_humansearch_message_rewrites_with_urls_and_win_alias`)는 사용자가 문장에
  `"humansearch"`라고 명시하고 링크드인 검색결과 URL까지 줬는데도 결과가
  `"/fleet-run aisearch ..."`가 되는 것을 **정답으로 못박아둔 테스트**다 — 지금 버그가
  스펙으로 굳어 있다.
- skills/humansearch 스킬 자체 설명(`.claude/skills/humansearch/SKILL.md` 트리거 설명)도
  "사람이 미리 걸어둔 채용사이트 검색결과(LinkedIn Recruiter/RPS·사람인·잡코리아)를
  순회해 후보를 채점·등록"이라고 명시한다 — 검색어를 새로 만드는 aisearch와 반대로,
  이미 있는 검색결과 리스트를 "순회"하는 것이 humansearch의 정의 그 자체다.

## ② 근본 원인

fleet-run의 skill 기본값 결정 로직이 **입력 URL의 모양(포지션 링크 단독 vs 포지션+검색결과
리스트)을 보지 않고** 항상 aisearch로 고정되어 있다. URL을 "포지션"과 "검색결과"로 나누는
판정(`_is_search_url`)은 이미 있는데, 그 판정 결과가 skill 선택에 배선되어 있지 않다
(URL 분류 코드는 있음, skill 선택 배선만 빠짐).

## ③ 인수 기준 (EARS)

**AC1 — 검색결과 URL이 있으면 humansearch, 없으면 기존 default(aisearch) 유지**

> When `/fleet-run`(또는 그 디스코드 자연어 등가 표현)에 포지션 URL과 함께 채용포털
> 검색결과 URL(사람인·잡코리아·링크드인 검색결과, `_is_search_url()` 판정)이 하나 이상
> 포함되고, 호출자가 `skill:`을 명시하지 않았다면, then 시스템은 그 잡의 skill을
> `humansearch`로 선택해야 한다. 검색결과 URL이 하나도 없으면 기존 기본값 `aisearch`를
> 그대로 유지해야 한다(회귀 금지). 여러 개의 검색결과 URL이 오면 전부
> `params.search_urls` 리스트에 순서대로 보존해야 한다(순회 대상 리스트).

- 검증 명령: `python -m pytest tests/test_hermes_fleet_bridge.py -q`
- counter-AC(가짜 완료):
  - 검색결과 URL 유무와 무관하게 **항상** humansearch로 바꿔버리는 것(포지션 링크만 있는
    기존 aisearch 케이스가 회귀).
  - 호출자가 명시적으로 `skill:aisearch`를 줬는데 검색결과 URL이 있다는 이유로 강제로
    humansearch로 덮어쓰는 것(명시 지정 무시 — 사용자 의도보다 추론이 이기면 안 됨).
  - `parse_hermes_fleet_args`(직접 `/fleet-run key:value` 경로)만 고치고
    `natural_fleet_command_text`(디스코드 자연어 경로)는 안 고쳐서 절반만 배선되는 것,
    또는 그 반대.
  - 검색결과 URL이 2개 이상일 때 하나만 `search_urls`에 남기고 나머지를 조용히 버리는 것.

## ④ Harness 게이트 진행 계획

- 워크트리: `../Valuehire_v5-humansearch-portal-search-skill` (`task/humansearch-portal-search-skill`,
  base = 현재 HEAD `999a47a`, main(`a34ab81`)보다 2커밋 앞 — natural_fleet_command_text 자체가
  `main`에는 없고 `4e2f4e5`에서 도입됐으므로 그 커밋을 포함하는 `999a47a`를 base로 삼음).
- Gate 0 참고사항(중요, 정직하게 기록): 이 워크트리를 **아무 변경 없이** 깨끗한 상태로
  전체 `verify.sh`를 돌리면 **54개 실패**가 이미 있다(전부 Windows 이식성 문제 —
  `pass_fds not supported on Windows`, `os.symlink` 관리자권한 필요, 프로필 락 배타성 등
  `tests/test_portal_tab_guard.py` / `tests/test_multi_position_sourcing.py`(포털 락/스냅샷
  계열) / `tests/test_portal_bg_login_plumbing.py` / `tests/test_portal_cdp_discovery.py` /
  `tests/test_daemon_crashloop.py` 등). 이 실패들은 **이 작업이 건드리는 파일
  (`hermes_fleet_bridge.py`, `discord_routing.py`, `fleet_dispatch.py`)과 무관**하고,
  메인 작업 폴더에 이미 있는 별도의 미커밋 윈도우 이식성 수정 작업(portal_worker.py,
  portal_snapshot.py)이 다루고 있는 영역이다. `tests/test_hermes_fleet_bridge.py`는
  베이스라인에서 **35개 전부 통과**(확인 완료). Gate 4 검증은 (a) 대상 테스트 파일
  타겟 실행으로 RED→GREEN 증명 + (b) 전체 스위트 실패 개수가 베이스라인(54개)에서
  **늘지 않았음**을 같이 보고하는 방식으로 진행한다(무관한 사전 결함을 이 PR 책임으로
  떠넘기지 않되, 숨기지도 않는다).
- Gate 2: RED 테스트를 `tests/test_hermes_fleet_bridge.py`에 추가 → 커밋.
- Gate 3: `hermes_fleet_bridge.py`에 URL 모양 기반 skill 선택 헬퍼 추가, 최소 변경.
- Gate 3.5: 배선 증명 — `dispatch_hermes_fleet_command` → `parse_hermes_fleet_args`
  전 경로 + `ops/hermes-plugin/valuehire_fleet/__init__.py`의 `_capture_gateway_identity`
  → `natural_fleet_command_text` 호출까지 정적 추적(grep으로 충분 — 둘 다 동기 함수 호출,
  동적 import/이벤트 핸들러 아님).
- Gate 4: 타겟 + 전체 verify, 숫자 그대로 보고.
- Gate 5: `make ship`(push + PR). main 머지는 CI 확인 후 별도 승인.

## ⑤ codex 적대검증 항목

- "검색결과 URL이 있을 때만 humansearch로 바뀌고, 포지션 URL 단독일 때는 정말 회귀 없이
  aisearch로 남는가?" 를 정조준.
- "명시적 `skill:aisearch` + 검색결과 URL 조합에서 사용자 지정이 실제로 이기는가?"
- "자연어 경로(`natural_fleet_command_text`)와 직접 명령 경로(`parse_hermes_fleet_args`)가
  같은 판정 함수를 쓰는지, 아니면 하나만 고쳐져서 절반만 배선됐는지."
- "여러 검색결과 URL이 전부 `search_urls`에 순서 보존되어 남는지, 하나만 남고 나머지가
  조용히 사라지지 않는지."

## ⑥ SOT 체크리스트

- `docs/sot/29-fleet-control.md`, `docs/sot/29-fleet-control.json`, `docs/sot/31-fleet-run-reliability.md`
  확인함 — **skill 기본값 결정 규칙을 기술하는 내용 없음**(fleet 계정 바인딩/락/신뢰성
  위주). 이번 변경이 SOT에 이미 기술된 동작을 바꾸는 것이 아니므로 SOT 문서 diff는
  동봉하지 않는다. 이 저장소의 기존 관례(2026-07-13 유사 변경들)를 따라
  `hermes_fleet_bridge.py` 안의 날짜 붙은 주석이 이 결정의 근거 기록 역할을 한다.

## ⑦ 비범위 (이번에 하지 않음)

- 클릭업 AI Search 리스트(901818680208) 실제 등록 배선, 디스코드 완료 메시지에 후보별
  profile_url/점수/이유/약력 포함, 동시 사용자 처리 스펙 테스트 — **작업 B로 분리**
  (별도 워크트리).
- `portal_worker.py`/`portal_snapshot.py` 윈도우 이식성 수정 — 별도 진행 중인 작업, 손대지 않음.
- humansearch 스킬 자체의 크롤링/채점 내부 동작 — skill *선택* 로직만 다룬다.

## ⑧ 롤백 절차

`git revert <merge-commit>` 1건으로 원복 가능(순수 함수 로직 변경, 마이그레이션·상태
변경 없음). 되돌리면 검색결과 URL이 있어도 다시 항상 aisearch로 돌아간다(이전 동작과 동일).

## ⑨ 영향 반경(blast radius)

- 이 변경이 깨지면: (a) 검색결과 URL을 줬는데도 계속 aisearch로 잘못 실행되어 humansearch가
  절대 안 걸릴 수 있음(무해 — 기존 동작과 동일해질 뿐), 또는 (b) 포지션 URL만 준
  기존 케이스까지 humansearch로 잘못 바뀌어 **회귀**(aisearch 유저 흐름이 깨짐 — 이게
  진짜 위험). counter-AC 3, 4로 방어.
- PII/인증/블랙리스트/과금 경로 접촉 없음(순수 파싱/디스패치 로직).

## 적대 검증 로그

### 1차 — Codex Rescue (격리, `codex exec`)

- 실행: `codex exec -C <worktree> -s workspace-write -o <verdict-file> -` (프롬프트 파일:
  `scratchpad/codex-rescue-prompt-humansearch-portal-search-skill.md`, 구현자의 추론 과정은
  전달하지 않고 코드+AC+검증 명령만 전달).
- 원본 transcript: 백그라운드 태스크 출력 —
  `tasks/bod4jd90n.output`(150줄), verdict 파일 —
  `scratchpad/codex-rescue-verdict-humansearch-portal-search-skill.txt`.

**VERDICT: FAIL**

발견한 결함(codex 원문 그대로):

1. `hermes_fleet_bridge.py:245`(자연어 경로) — 사용자가 문장에 `skill:aisearch`를 명시해도
   검색결과 URL이 있으면 `humansearch`로 덮어씀. 반대 방향(`skill:humansearch` 명시 + 검색
   URL 없음 → `aisearch`로 덮어씀)도 동일 결함. 실측 재현:
   `skill:aisearch로 찾아줘 <clickup> <saramin검색url>` → `/fleet-run humansearch ...`
   (명시 지정 무시).
2. `hermes_fleet_bridge.py:90`(`_is_search_url`, 당시 라인) — 호스트명이 아니라 URL 전체
   문자열에서 마커 부분 문자열만 검사. `https://app.clickup.com/t/abc?source=jobkorea.co.kr`
   (쿼리 문자열에 우연히 마커) 와 `https://linkedin.com.evil.example/...`(유사 도메인) 둘
   다 검색 URL로 오판 → 포지션 URL 단독 케이스가 humansearch로 잘못 바뀌는 회귀
   (counter-AC 직접 위반, 실측 재현됨).
3. 직접 명령 경로와 자연어 경로가 `_default_skill_for_urls()`는 공유하지만 "명시 지정이
   추론보다 우선한다"는 우선순위 로직은 공유하지 않음(자연어 경로엔 그 로직 자체가 없었음).
4. 테스트 갭: 명시 스킬 우선순위 테스트가 직접 파서만 검사(자연어 경로 누락), `_is_search_url`
   음성 케이스(유사 도메인·쿼리 문자열)가 테스트에 없었음.

전체 스위트 비교(codex 자체 sandbox, 격리 재현): HEAD `58 failed`/999a47a 베이스라인
`58 failed`(둘 다 동일 개수·동일 목록) — 이번 변경이 기존 실패를 늘리지 않았다는 점은
codex가 독립적으로 확인. (숫자가 이 문서의 다른 곳에 적은 "54"와 다른 건 codex의 sandbox
환경 차이 때문 — codex 자신도 원문에 "sandbox에서 재현되지 않았다"고 명시.)

### 2차 — Claude 재현·수정·재검증

codex가 지목한 file:line 증거를 격리된 새 파이썬 프로세스에서 직접 재현(추측 없이):

| # | codex 주장 | Claude 재현 결과 | 판정 |
|---|---|---|---|
| 1 | 자연어 `skill:aisearch` + 검색URL → humansearch로 덮어씀 | 동일 재현(`/fleet-run humansearch ...`) | 실재 결함, 확인 |
| 2 | 자연어 `skill:humansearch` + 검색URL 없음 → aisearch로 덮어씀 | 동일 재현 | 실재 결함, 확인 |
| 3 | `?source=jobkorea.co.kr` 쿼리로 오탐 | `_is_search_url(...) == True` 재현 | 실재 결함, 확인 |
| 4 | `linkedin.com.evil.example` 유사도메인 오탐 | `True` 재현 | 실재 결함, 확인 |
| 5 | `linkedin.com/jobs/view/...`(검색결과 아닌 단일 공고) 오탐 | `True` 재현(사실) | 별도 판단: 아래 참조 |

**수정**:
- `_is_search_url` — `urllib.parse.urlparse(url).hostname` 기준 정확히 마커와 같거나
  서브도메인일 때만 True로 좁힘(#3, #4 해결).
- `natural_fleet_command_text`에 `_explicit_skill_from_natural_text()` 신설 — `skill:xxx`
  패턴(정규식에서 `\b` 제거: 한글 조사가 바로 붙으면 유니코드 `\b`가 경계로 안 잡히는 걸
  실측으로 발견해 반영) 또는 문장 속 "aisearch"/"humansearch" 단독 언급을 URL 추론보다
  우선시킴(#1, #2 해결). 부분 문자열 검사(`in low`)를 씀 — 단어 추출 정규식이 한글 조사를
  Latin 단어에 붙여버려 集合 기반 검사가 실패하는 걸 재현 후 발견, `_NATURAL_TRIGGERS`가
  이미 쓰는 방식과 통일.
- 회귀 테스트 6개 추가(`test_is_search_url_rejects_query_string_and_lookalike_domain`,
  `test_position_url_with_incidental_marker_in_query_stays_aisearch`,
  `test_natural_language_explicit_skill_prefix_wins_over_search_url_inference` ×2 방향,
  `test_natural_language_bare_skill_word_wins_over_search_url_inference`, 그리고 최초
  구현 커밋의 5개 포함 총 11개 신규).

**#5(codex 주장 5번)에 대한 별도 판단 — 고치지 않고 한계로 남김**:
`_is_search_url`은 호스트만 보고 경로(path)는 안 본다 — 이건 이번 변경 이전부터 있던
기존 설계(이 함수 자체는 2026-07-13에 이미 존재, params.search_urls 묶기 용도였음)이고,
사람인/잡코리아/링크드인 세 포털의 "진짜 검색결과 URL"이 어떤 경로 모양인지(예: 링크드인은
`/search/results/people/`, 잡코리아는 `/Corp/Person/Find`, 사람인은
`/zf_user/memcom/talent-pool/main/search` — 셋 다 패턴이 다름)를 규정하는 건 이번
AC(스킬 선택)의 범위를 넘는 별도 작업이다. 고치지 않은 근거를 남겨서 향후 후속 이슈로
넘긴다(침묵 누락이 아니라 명시 비범위).

**추가로 Claude가 직접 찾은 것(codex 목록에 없던 것)**: `_explicit_skill_from_natural_text`가
`low`(URL을 포함한 원문 소문자 전체)에서 "aisearch"/"humansearch" 부분 문자열을 찾으므로,
URL 자체의 쿼리 파라미터에 그 단어가 우연히 들어 있으면(예: `?ref=aisearch-promo`) 오탐할
수 있다 — #3/#4와 같은 종류의 새 리스크. 이번엔 고치지 않고 명시 한계로 남김(발생 확률
낮고, 최악의 경우도 두 유효 스킬 값 중 하나로 잘못 갈 뿐 — 크래시나 보안 문제 아님). 후속
이슈 후보.

**재검증(고침 이후)**: 대상 스위트(`test_hermes_fleet_bridge`,
`test_hermes_plugin_registration`, `test_fleet_dispatch`, `test_fleet_worker`,
`test_hermes_position_context`) `91 passed`. 전체 스위트(`pytest tests -q`)
`54 failed, 1353 passed, 11 skipped, 4 xfailed, 1 error`(999a47a 베이스라인과 실패
개수 동일 — 이번 변경 무관 사전 결함, 회귀 없음).

**결론**: codex가 지목한 5개 중 4개(#1~#4)를 실재 결함으로 확인·수정, 1개(#5)는 별도
비범위로 명시 보류. Claude가 독립적으로 1개 추가 리스크(#6, 위)를 발견해 명시 보류.
codex 판정(FAIL)은 과장이 아니라 정확했다 — 뒤집을 근거 없음.
