# Login-first search execution contract

상태: 실행 프롬프트 정본

적용: Claude · Codex

정책 권위: `docs/sot/26-portal-login-spec.json` (`26-portal-login-spec@1.5.0`)

이 문서는 로그인 구현이 아니라 로그인 잡과 검색 잡이 따라야 할 정책 연결 계약입니다.
APP 01은 기존 런타임을 안전하다고 보증하지 않습니다. 정책과 충돌하는 과거 실행기는
후속 구현 단위가 교체할 때까지 호출하지 않습니다.

관련 정본:

- `docs/sot/26-portal-login-spec.json`
- `skills/login/browser-control-contract.json`
- `skills/login/SKILL.md`
- `tools/multi_position_sourcing/fleet_worker.py`의 생성 프롬프트

검색 모델은 모든 필수 사이트가 정책에 맞게 `READY`로 증명되기 전 브라우저 검색을
시작하지 않습니다.

## 입력

```json
{
  "request_id": "discord:<message-id>",
  "skill": "login|aisearch|humansearch|url",
  "agent": "Claude|Codex",
  "target_id_by_site": {},
  "position_url": "",
  "search_urls": []
}
```

같은 `request_id`는 한 번만 처리합니다. 비밀번호·쿠키·토큰·비밀 원문이나 파생값은
입력, 명령행 인자, 모델 메시지, stdout, stderr, 로그, 영수증, 산출물에 넣지 않습니다.

## 필요한 사이트

| skill | 로그인 점검 대상 |
|---|---|
| `login` | 요청에 지정된 사이트, 미지정이면 사람인·잡코리아·LinkedIn RPS |
| `aisearch` | 사람인·잡코리아·LinkedIn RPS |
| `humansearch` | `search_urls`에서 실제 사용하는 사이트만 |
| `url` | LinkedIn RPS |

## 사이트별 인증 결정

인증 조작 전에 기존 브라우저, endpoint, 프로필, 정확한 기존 target 후보 수를 읽기
전용으로 증명합니다. 대상 후보가 정확히 1개가 아니면 임의로 고르지 않습니다.
관리 브라우저 부재(`managed_browser_missing`)나 정확한 target 부재는 `HANDOFF`입니다.
로그인 흐름은 새 브라우저 0개, 새 창 0개, 새 탭 0개이며, 고정 좌표나 화면문자 인식
기반 클릭을 인증 수단으로 사용하지 않습니다.

| 사이트 | 허용 인증 | 실패 방향 |
|---|---|---|
| 사람인 | 정확한 기존 target 후보가 1개일 때 저장 아이디·비밀번호 최대 1회 | 후보 0개/복수 또는 제공자 없음은 인증 조작 0회 `HANDOFF`; captcha·2FA·checkpoint는 `HUMAN_AUTH` |
| 잡코리아 | 정확한 기존 target 후보가 1개일 때 저장 아이디·비밀번호 최대 1회 | 후보 0개/복수 또는 제공자 없음은 인증 조작 0회 `HANDOFF`; captcha·2FA·checkpoint는 `HUMAN_AUTH` |
| LinkedIn RPS | 인증 기기 1개면 그 기기의 유일한 target을 인증 조작 0회 재사용. 인증 기기 0개로 증명됐고 현재 턴 승인과 APP 17 경로 결정이 같은 기기를 가리키며 정확 후보가 1개일 때만 APP 30/31의 `LINKEDIN_LI_AT` 적용을 최대 1회 허용 | 인증 기기 수 미증명·정확 후보 0개/복수·APP 30/31 미준비는 인증 조작 0회 `HANDOFF`; 인증 기기 2개 이상 또는 멀티세션은 terminal `AUTH_CONFLICT` |

LinkedIn 아이디·비밀번호 제출, 공식 로그인 URL 이동, 새 target 생성, 다른 기기 자동
로그아웃, Continue/Confirm, 신뢰도 기반 기기 선택, 재시도는 금지합니다.
모든 사이트에서 보안 탐지 우회와 반복 제출도 금지합니다.

## LOGIN_BARRIER

검색 잡을 모델에 넘기기 전에 다음 순서로 판정합니다.

1. 필요한 사이트와 현재 요청의 정확한 실행 기기를 확정합니다.
2. 알려진 관리 브라우저의 endpoint·프로필·기존 target을 읽기 전용으로 조사합니다.
3. 사람인·잡코리아는 정확 후보 1개에서만 사이트별 저장 자격증명을 최대 1회 허용합니다.
4. LinkedIn은 봉인된 함대 증거로 인증 기기 수를 먼저 증명하고 위 0·1·2+ 결정표를
   적용합니다. 소유자 승인은 기기 수 증거가 아니며 APP 17의 경로 결정과 일치해야 합니다.
5. 실제 captcha·2FA·checkpoint는 정확한 창을 한 번만 표시하고 `HUMAN_AUTH`로
   전이합니다. 사람이 처리하는 동안 click·type·navigate·reload·focus는 0회입니다.
6. LinkedIn multiple-sign-in·Only one session·enterprise-authentication은
   `AUTH_CONFLICT`입니다. 사람 인증 인계로 바꾸지 않습니다.
7. fresh 로그인 마커와 정확한 기존 target을 함께 증명한 사이트만 `READY`입니다.
8. 모든 필수 사이트가 `READY`일 때만 검색을 시작합니다.

PAUSED_FOR_HUMAN은 실제 HUMAN_AUTH에서만 사용할 수 있습니다.
HANDOFF·AUTH_CONFLICT에는 사용하지 않는다 가 고정 규칙입니다. 두 상태는 완료 영수증도
내지 않고 정확한 상태와 근거를 보고해 종결합니다. 시간 경과나 60초 대기로 자동
재개하지 않습니다.

## 영수증

사이트별 영수증은 비밀 필드를 허용하지 않습니다.

```json
{
  "site": "saramin|jobkorea|linkedin_rps",
  "state": "READY|HUMAN_ACTIVE|HUMAN_AUTH|AUTH_CONFLICT|HANDOFF",
  "target_id": "exact target id or null",
  "proof_names": [],
  "last_verified_at": "ISO-8601",
  "browser_mutations": 0,
  "secret_fields": 0
}
```

모든 필수 사이트가 `READY`일 때만 다음 영수증을 냅니다.

```text
LOGIN_BARRIER=PASS request_id=<id> sites=<comma-separated-sites>
```

하나라도 준비되지 않았으면 검색은 시작하지 않고 사이트별 `HUMAN_AUTH`, `HANDOFF`,
`AUTH_CONFLICT`를 보존해 보고합니다.

## SEARCH_EXECUTION

`LOGIN_BARRIER=PASS` 이후에만 지정된 `aisearch`, `humansearch`, `url` 작업을
실행합니다. 검색 에이전트에는 사이트별 endpoint와 exact target id만 넘깁니다.

검색 중 로그인 마커가 사라지면 해당 사이트를 `AUTH_LOST`로 바꾸고 즉시 위 결정표를
다시 적용합니다. 검색 결과 0명으로 위장하거나 다른 비공식 채널로 대체하지 않습니다.

## 보호 Hook이 막았을 때

현재 보호 Hook은 레거시·불완전하며 정책 권위가 아닙니다. Hook을 끄거나 명령을
난독화하지 않습니다. 실제 captcha·2FA·checkpoint가 양성 확인된 경우에만 정식
`session_guard human-auth`를 사용할 수 있습니다. 일반 로그아웃, 제공자 미구현,
인증 기기 수 미증명, 정확 후보 부재에는 `HUMAN_AUTH`로 우회하지 않고 `HANDOFF`합니다.

## 종료 보고

```text
로그인: <site>=<READY|HUMAN_ACTIVE|HUMAN_AUTH|HANDOFF|AUTH_CONFLICT> (마커: <proof names>)
검색: <STARTED|NOT_STARTED>
브라우저 보존: 창/탭/프로필 종료 0건, CDP 연결만 해제
```
