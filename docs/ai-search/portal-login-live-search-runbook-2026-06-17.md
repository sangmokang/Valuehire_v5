# 포털 로그인 + 라이브 서치 표준 런북 (2026-06-17 검증)

> 사장님 지시(2026-06-17): "이 프로세스를 아주 명확하게 search, multisearch, 사람인·잡코리아·링크드인 로그인해야 하는 **모든 작업**에 기억해둬."
> 이 문서는 2026-06-17 ClickUp 포지션 3건(86exu1gap / 86ew25gkz / 86ew25gma) 실행에서 **실제로 통과·검증된 절차만** 적었다. 추측은 "미확정"으로 표기한다.
> 적용 대상 스킬: `search`, `multisearch`, `saramin-talent-sourcing`, `jobkorea-talent-sourcing`, `linkedin-rps-jd-set-builder`, `position-register`, `position-batch-flow`, `talent-search` — 즉 3사 로그인을 건드리는 모든 작업.

---

## 0. SOT 불변식 (절대 약화 금지)

- 3사(사람인·잡코리아·링크드인) **자동 로그인을 막지 않는다.**
- **보안 챌린지(캡차·2FA·checkpoint·이상접근)는 절대 자동 우회하지 않는다** — visible browser에서 사람이 풀 때까지 멈춤.
- **사장님이 직접 로그인하면 그 세션을 절대 닫지 않는다(끄지마) / 세션 유지.**
- 제안·메일·InMail **발송은 자동으로 누르지 않는다** — 사람이 마지막에 누름.
- 보내는 **profile URL은 절대 틀리면 안 된다** — 실제로 열어 이름 일치 확인한 것만.
- 사장님께는 **쉬운 한국어**로 보고.

---

## 1. 로그인 (3사) — 끄지마 규칙

### 1-1. 프로필이 어디에 사는가 (중요 — 분리됨)
- **링크드인**: 사장님 메인 크롬(CDP `http://127.0.0.1:9222`)에 **attach**. 연결만 끊을 뿐 브라우저/탭을 **안 닫음**. → 끄지마 자동 충족.
- **사람인·잡코리아**: `launch_persistent_context` 별도 영속 프로필(`~/.valuehire/portal_profiles/<site>/<worker>`). 쿠키가 디스크에 저장되어 **다음 실행에 재사용**됨. 단 `PortalWorker.stop()`의 `context.close()`가 창을 닫음(portal_worker.py:516) → 창을 유지하려면 같은 프로세스에서 열고 `context.close()`를 호출하지 않는다.
- **MCP claude-in-chrome 확장은 9222 디버그 크롬에 안 붙는다** → 사람인/잡코리아는 MCP 말고 **CDP playwright 직접**으로 다룬다.

### 1-2. 로그인 확인/실행
```bash
python3 -m tools.multi_position_sourcing.portal_login \
  --channels saramin,jobkorea,linkedin_rps \
  --profile-root ~/.valuehire/portal_profiles --worker-id default \
  --chrome-cdp-endpoint http://127.0.0.1:9222 \
  --channel-timeout-seconds 0 --human-timeout-seconds 1800 \
  --output artifacts/portal_session_status_latest.json
```
- **`--channel-timeout-seconds 0` (가드 비활성) + 충분한 `--human-timeout-seconds`** 필수.
  - 이유: channel-level timeout이 사람 개입 대기보다 짧으면 `asyncio.wait_for`가 **사장님 로그인 도중 창을 강제 종료**한다(2026-06-17 실제 발생: 180 < 240 → 180초에 잘림).
- 결과 확인: `portal_sessions[].login` 이 `existing_session_ok` 또는 `human_intervention_ok` 면 ready.
- 링크드인 자동로그인 자격증명은 **미설정**(`credentials_not_configured`) → 사장님이 직접 로그인해야 함. 로그인 탭은 CDP로 띄우고(안 닫힘) 사장님 로그인 후 재확인.

### 1-3. 창을 띄운 채 유지(끄지마) + 그 안에서 검색
한 프로세스에서 `PortalWorker.start()`로 3사 창을 열고, **`stop()`/`context.close()`를 부르지 않고** 그 안에서 `run_one_search`를 돌린 뒤 sleep 루프로 창을 유지한다(영속프로필은 한 프로필=한 프로세스라, 창 유지 프로세스와 검색 프로세스를 분리하면 flock 충돌). 참고 구현: `artifacts/live_search_driver.py`.

---

## 2. 라이브 수집 안정성 (검증된 교훈)

- **LinkedIn Recruiter 결과는 JS 렌더가 느리다 — 검색 직후 1초만 기다리면 0건(실제 발생).**
  - 고치는 법: 결과 selector `a[href*="/talent/profile/"]`가 뜰 때까지 **최대 ~15초 `wait_for_selector` + 스크롤** 후 수집.
  - selector 자체는 정상. 계정 "Value Connect - RPS"는 정상 Recruiter(검색결과 3.8M+).
  - 진입 URL: `https://www.linkedin.com/talent/search?searchKeyword=<kw>&start=0`, Boolean `("A" OR "B") AND (지역)`로 JD 전체 포괄.
  - 행 전체정보(직함·회사·지역)는 profile 링크의 **조상 `li`/row innerText**로 긁는다(이름만으론 점수 못 냄).
- **사람인**: talent-pool이 `main/tutorial`로 빠지거나 인증 리다이렉트로 `login_redirect` not_ready **오탐**이 날 수 있다. 기업회원 URL(`ut=c`)로만 진입하고 검색화면 마커(`input.search_input`/`#career_min`/`#career_max`) 도달을 직접 확인. (2026-06-17 사람인 라이브 수집은 **미확보** — 채널 제한.)
- **잡코리아**: 검색화면(`Corp/Person/Find`) 도달했으나 결과 카드 0건. 결과 selector가 인재검색 결과 DOM과 맞는지 **실페이지로 확인 필요**(원인 미확정 — selector인지 결과없음인지 단정 금지). (2026-06-17 **미확보**.)
- 채널이 막혀 0건이면 "후보 없음"이 아니라 **"채널 제한으로 미확보"**로 보고.

---

## 3. 후보 선별 + URL 무결성 (사장님 hard rule)

1. 원시 수집엔 **직무·지역 무관 후보가 섞인다**(예: JP PM 검색에 인도/파리, 북미 마케터에 필리핀). → **직무·지역·연차로 선별**해서만 내보낸다.
2. 점수 축: JD must-have 직결 · 연차 · 회사 신호 · 지역/언어 · 근거 품질 · 리스크.
3. **보낼 모든 profile URL을 실제로 열어 이름이 페이지에 있는지 전수 확인**한다(2026-06-17: 15/15 일치 확인 후 발송). 페이지 href를 그대로 복사 → 매핑도 정확.

---

## 4. codex 1차 + Claude 2차 적대검증 (필수)

- `codex:codex-rescue`로 1차: "가짜 완료/과장/URL 오류" 정조준. 판정 본문(VERDICT + 결함)을 보존.
- Claude 2차: codex 근거를 **직접 재현**하고 PASS/FAIL을 **양방향**으로 재공격. 교차표로 일치/불일치 공개.
- 2026-06-17 사례: codex VERDICT=FAIL(원시결과 부적합 후보 혼입·잡코리아 원인 추정·URL 재현불가). 내 재현 → 선별로 해결 + URL 15/15 재현 성공(codex의 "재현불가"는 codex 환경한계로 무효) + 잡코리아 "원인 미확정"으로 정정.

---

## 5. 디스코드 발송 (결과 보고 — 발송 아님)

- 채널: `.env.local`의 **`VALUEHIRE_SEARCH_LIST_DISCORD_WEBHOOK_URL`** (AI Search 최종 리스트 전용). 웹훅 URL은 **출력하지 않는다.**
- 헤더에 **User-Agent** 포함(403 회피). `flags:4`로 임베드 억제.
- 메시지 4종 필수: **Profile URL · 점수 · 잘 맞는 점 · 후보자 프로필 요약** (+ 리스크/확인필요, 대상 포지션 ClickUp URL). 하나라도 없으면 보류.
- 포지션당 메시지 1개로 2000자 제한 회피. 2026-06-17 발송 3건 모두 status 204.

---

## 6. 완료 기준

- 로그인 3사 ready(증거: portal_sessions login 값).
- 보낸 후보 URL **전수 열어 이름 일치**.
- codex 1차 + Claude 2차 교차검증 통과.
- 디스코드 발송 status 204.
- 미확보 채널은 정직히 "채널 제한"으로 명시.
- **끄지마**: 사장님 로그인 세션/창 유지(영속프로필 디스크 보존 + 가능하면 창도 유지).
