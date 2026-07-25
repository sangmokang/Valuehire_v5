# LinkedIn 관리 브라우저 자동 로그인 실증 목표 — 2026-07-26

Issue: #210

## 현재 상태와 근본 원인

- `session_guard.resolve_managed_browser_process()`는 명령행의 포트만 비교해,
  IPv4 LinkedIn Chrome과 IPv6 사람인 Chrome이 모두 `9225`를 선언하면 둘을
  구분하지 못했다 (`tools/multi_position_sourcing/session_guard.py`).
- 기존 LinkedIn `login-cap` 탭에 로그인 폼이 있어도
  `perform_autologin()`은 무조건 `/uas/login`으로 이동했다. 2026-07-26 Mac mini
  실측에서 이 주소는 입력 폼 대신 `새로고침` 버튼만 있는 연결 오류 화면이 됐다
  (`tools/multi_position_sourcing/portal_selfservice_login.py`).
- 첫 라이브 시도는 프로세스 2개 모호성으로 중단했고, 두 번째 시도는
  `SELECTOR_DRIFT(inputs=0, forms=0, buttons=["새로고침"])`로 중단했다.
  기존 탭의 자격증명 제출은 0회였다.
- 수정 후 공용 Keychain을 직접 읽는 실제 실행은 보안문자/CAPTCHA를 제출 0회
  `HUMAN_AUTH`로 판정했다. 정확한 창 표시 시 visible marker 설치가 실패해
  브라우저를 focus하지 않고 종료했으며, 사람 인증 완료는 아직 미실증이다.
- 재발 장부 관련 행: `로그인 지시 미이행`, `로그인창 못 찾고 배회`
  (`valuehire_v4/docs/sot/31-strict-recurrence-ledger.md`). 두 항목 모두 반복 2회다.

## 인수 기준

EARS: Mac mini에서 동일 CDP 포트를 선언한 두 Chrome이 공존하고 LinkedIn의 기존
`/uas/login-cap` target이 있을 때, 정식 `session_guard auto-login`은
`127.0.0.1:<port>`의 실제 LISTEN PID와 exact target을 선택하고, 현재 target에
자격증명 필드가 있으면 다른 로그인 URL로 이동하지 않으며, 인증 성공 또는
검증된 `HUMAN_AUTH` 상태를 비밀값 노출 없이 반환해야 한다.

Counter-AC: 다른 PID/profile 선택, 새 browser/window/tab 생성, captcha/2FA/
checkpoint/멀티세션 자동 우회, 비밀번호 출력, 챌린지에서 제출 1회 이상은 실패다.

## 작업 단위

| 단위 | 계약 | 검증 | 의존 |
|---|---|---|---|
| A | endpoint의 실제 IPv4 LISTEN PID로 중복 명령행 후보를 1개로 축소 | exact-listener 회귀 검사 | 없음 |
| B | 기존 LinkedIn login-cap에 id/password 필드가 있으면 현재 target에서 제출 | existing-form 회귀 검사 | A |
| C | SOT-26과 Claude/Codex login 스킬이 같은 `session_guard auto-login` 진입점을 지시 | 계약·스킬 검사 | A, B |
| D | 기존 Mac mini target 라이브 실행 결과가 AUTHENTICATED 또는 실제 HUMAN_AUTH | 라이브 JSON 결과·영수증 | A, B, C |

## 입력 영역과 처리

| 입력 | 사례 | 처리 |
|---|---|---|
| endpoint | `http://127.0.0.1:<port>` | 해당 IPv4 LISTEN PID만 허용 |
| 프로세스 | 같은 port 선언 1개 | 기존 PID/profile 사용 |
| 프로세스 | 같은 port 선언 여러 개, IPv4 listener 1개 | listener PID로 1개 선택 |
| 프로세스 | listener 0개/여러 개 또는 `lsof` 실패 | 명시적 중단 |
| target | 정확한 기존 target id 1개 | raw CDP 단일 target attach |
| target | 없음/중복/바뀜 | 새 탭 없이 명시적 중단 |
| 현재 화면 | authenticated marker | 조작 0회, AUTHENTICATED |
| 현재 화면 | login-cap + id/password 필드 | 현재 폼 사용, URL 이동 0회 |
| 현재 화면 | 일반 로그인, 기존 필드 없음 | SOT 로그인 URL로 동일 target 1회 이동 |
| 현재 화면 | 연결 오류/필드 없음 | SELECTOR_DRIFT, 제출 0회 |
| 현재 화면 | captcha/2FA/checkpoint/멀티세션 | HUMAN_AUTH/AUTH_CONFLICT, 제출·우회 0회 |
| 자격증명 | 둘 다 존재 | 프로세스 메모리 안에서만 사용 |
| 자격증명 | 누락 | missing_credentials로 중단 |
| 사람 점유 | 포털 화면 최근 조작 | HUMAN_ACTIVE로 양보 |
| 재시도 | 같은 실패를 원인 변경 없이 반복 | 금지, `failed_attempts`에 기록 |
| 그 외 전부 | 표 밖 상태 | 명시적 중단 후 이 표와 회귀 사례 갱신 |

## 결정 목록

- 동일 endpoint의 실제 소유자는 명령행 포트가 아니라 정확한 IPv4 LISTEN PID로 정한다.
- 기존 login-cap 폼은 username과 password selector가 모두 현재 DOM에 있을 때만
  재사용한다. 둘 중 하나라도 없으면 채우지 않는다.
- `/uas/login-cap` URL 자체는 보안 챌린지가 아니다. 페이지 본문/URL의 결정적
  captcha·2FA·checkpoint·멀티세션 신호가 있을 때만 사람 인증으로 넘긴다.
- 로그인 성공은 `/talent/` URL 하나가 아니라 fresh Recruiter DOM marker와
  증거 영수증으로 판정한다.

## 상태 전이와 출력

`DISCOVER -> AI_ATTACHED -> AUTHENTICATED | HUMAN_AUTH | AUTH_CONFLICT | HANDOFF`

공개 출력은 `state`, `site`, `mutations`, `target_id`, `host`, 비밀 없는 진단만
허용한다. username/password/cookie/storage 값은 출력·산출물에 넣지 않는다.

## 검증 명령

```bash
./.venv/bin/python -m pytest -q \
  tests/test_login_session_runner.py tests/test_selfservice_autologin.py
./verify.sh
make strict-exit-gate
```

라이브 검증은 기존 target id를 명시한
`python -m tools.multi_position_sourcing.session_guard auto-login`만 사용한다.

## 비범위

- 새 Chrome/창/탭 시작
- 기존 stale 탭 정리 또는 종료
- captcha/2FA/멀티세션 자동 해결
- LinkedIn 외 검색·제안·발송

## SOT 체크리스트

- [x] SOT-26 INV1~INV3: 기존 관리 browser/target, 자동 로그인, 챌린지 사람 인계
- [x] SOT-26 INV5: raw CDP exact target
- [x] SOT-30 R3: 손 조작은 정식 runner만 수행
- [x] 재발 원장의 로그인 미이행·창 배회 사례를 회귀 검사로 승격
- [x] SOT-26/Claude/Codex 스킬 동기화
- [ ] 전체 검증·적대 검증·라이브 실증·배송
