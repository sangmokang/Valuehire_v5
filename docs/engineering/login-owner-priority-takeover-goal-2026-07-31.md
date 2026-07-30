# $login — 오너 명시적 기기 전환 + 로그인 최우선 순위 goal

> 근거: 2026-07-31 사장님 지시 2건. 둘 다 `.claude/skills/login`(및 `.codex/skills/login`,
> `~/.hermes/skills/login` 미러) + `docs/sot/26-portal-login-spec.json` + 코드
> (`tools/multi_position_sourcing/{session_guard,portal_selfservice_login,portal_login,owner_activity}.py`)
> 전체에 걸친 안전규칙 변경이다.

## AC-A — 오너가 명시한 기기에서는 세션 충돌을 막지 않고 로그인 진행

**현재 상태(file:line)**: `tools/multi_position_sourcing/portal_login.py:116-128`의
`_CHALLENGE_TOKENS`가 진짜 보안챌린지(captcha/2FA/checkpoint)와 세션충돌 전용 문구
(`multiple sign-ins`, `only one session`, `enterprise-authentication`)를 구분 없이 섞어
`_has_security_challenge()` 하나로 판정한다. `portal_selfservice_login.py:167-170`의
`perform_autologin`은 이 판정이 참이면 무조건 `HUMAN_AUTH`로 멈추고 제출 0회다 — 세션충돌도
진짜 챌린지와 동일하게 취급되어 예외 없이 멈춘다.

**요구사항**: 사장님이 특정 기기에서 명시적으로 로그인을 명령하면(`--owner-takeover` 플래그),
그 기기에서는 세션 충돌 신호를 이유로 멈추지 않고 자격증명 제출까지 진행한다(링크드인 자체가
새 기기 로그인 시 기존 세션을 무효화하므로, 별도로 "로그아웃 API"를 호출할 필요는 없다 —
제출을 막지 않는 것만으로 충분하다). **진짜 보안챌린지(captcha/2FA/checkpoint)는 이 플래그와
무관하게 항상 멈춘다** — 이건 사장님이 바꾸라고 한 대상이 아니다.

- Counter-AC: `--owner-takeover` 없이 실행하면 세션충돌 시 지금처럼 그대로 멈춰야 한다(회귀 금지).
- Counter-AC: `--owner-takeover`가 있어도 captcha/2FA/checkpoint 신호가 있으면 여전히 멈춰야 한다.

## AC-B — 로그인 화면 자체가 아니면 오너 활동 중이어도 로그인 최우선 진행

**현재 상태(file:line)**: `tools/multi_position_sourcing/owner_activity.py:39`
`PORTAL_HOSTS = ("saramin.co.kr", "jobkorea.co.kr", "linkedin.com")` 판정은 **호스트만** 보고
(§71 프라이버시 불변식 — 전체 URL/경로는 안 읽음), `session_guard.py`의
`run_auto_login_episode`(`session_guard.py:2311` 부근)는 `snapshot.owner_activity_detected`가
참이면 **로그인을 포함해** 무조건 양보한다. 즉 사장님이 3사 도메인의 아무 페이지(예: 사람인
채용공고 화면)를 보고만 있어도 로그인 자동화가 멈춘다.

**요구사항**: 로그인만은 예외로 최우선 처리한다 — 사장님이 **그 사이트의 로그인 화면 자체**를
조작 중일 때만 양보하고, 3사 도메인의 다른 화면(검색·채용공고 등)을 보고 있는 것은 로그인
자동화를 막지 않는다.

**설계 결정(중요)**: 이건 §71 프라이버시 불변식("페이지 내용·전체 URL은 안 봄")과 정면으로
부딪힌다. 완화 범위를 최소로 좁힌다 — 전체 URL/쿼리는 여전히 안 읽고, **사이트별로 미리 정해둔
로그인 경로 접두어 목록**(사람인 `/zf_user/auth`, 잡코리아 `/Login`, 링크드인 `/uas/login`,
`/checkpoint`, `/authwall`)과 현재 경로가 일치하는지만 boolean으로 확인한다. 이 목록 밖 상황은
"로그인 화면 아님"으로 fail-closed 취급(즉 양보 안 함 방향이 아니라, 판정 실패 시 안전하게
"로그인 화면일 수 있음"으로 보수적으로 양보 — 사람 보호가 항상 우선).

- Counter-AC: 3사 로그인 페이지 자체를 사람이 만지고 있으면 여전히 100% 양보해야 한다(핵심 안전 불변).
- Counter-AC: 판정 실패(에러)는 "양보 안 함"이 아니라 "양보함"으로 fail-closed.

## 계약

- `perform_autologin(..., owner_takeover: bool = False)`, `session_guard.py`의
  `run_auto_login_episode(..., owner_takeover: bool = False)`, CLI `auto-login --owner-takeover`.
- `owner_activity.py`에 `is_owner_on_login_screen(site, active_tab_path) -> bool` 추가(경로
  접두어 allow-list 매칭, 목록 밖/판독불가는 True로 fail-closed).
- `run_auto_login_episode`의 양보 게이트를 "호스트 활동" 단일조건에서
  "호스트 활동 AND 로그인화면 여부"로 교체(로그인 태스크 한정 — 다른 태스크의 양보 게이트는 불변).

## 비범위

- `run_human_auth_episode`(`$login human-auth`, 사람이 이미 챌린지를 처리 중인 흐름)의
  AUTH_CONFLICT 처리는 바꾸지 않는다 — 그건 "사람이 이미 넘겨받은 뒤"의 흐름이라 이번 지시
  ("명시적으로 기기를 지정해 로그인 명령")의 대상이 아니다. AC-A는 `auto-login`(자동 실행) 경로만.
- 잡코리아/사람인의 "세션 충돌" 개념 자체(멀티세션 로그인)는 실제로 없다 — AC-A는 사실상
  링크드인에만 적용된다(다른 사이트는 `_CHALLENGE_TOKENS`에 세션충돌 토큰이 원래 없음).

## 적대 검증 로그

(작성 중 — 구현 후 RED/GREEN pytest 출력을 이 절에 append)
