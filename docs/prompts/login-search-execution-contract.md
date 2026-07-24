# Login-first search execution contract

상태: 실행 프롬프트 정본  
적용: Claude · Codex · Hermes  
코드 정본:

- `skills/login/browser-control-contract.json`
- `tools/multi_position_sourcing/session_guard.py`
- `tools/multi_position_sourcing/raw_cdp.py`
- `tools/multi_position_sourcing/owner_activity.py`
- `.claude/hooks/guards/login.py`

이 프롬프트의 목적은 로그인을 모델의 즉흥 판단에서 분리하는 것입니다. 검색 모델은
`LOGIN_BARRIER=PASS` 영수증을 받기 전 브라우저 검색을 시작하지 않습니다.

## 입력

```json
{
  "request_id": "discord:<message-id>",
  "skill": "login|aisearch|humansearch|url",
  "agent": "Claude|Codex|Hermes",
  "target_id_by_site": {},
  "position_url": "",
  "search_urls": []
}
```

같은 `request_id`는 한 번만 처리합니다. 비밀번호·쿠키·토큰은 입력과 출력에 넣지
않습니다.

## 필요한 사이트

| skill | 로그인 점검 대상 |
|---|---|
| `login` | 요청에 지정된 사이트, 미지정이면 3사 |
| `aisearch` | 사람인·잡코리아·LinkedIn RPS |
| `humansearch` | `search_urls`에서 실제 사용 사이트만 |
| `url` | LinkedIn RPS |

사이트마다 `login-<site>.lock`을 먼저 획득합니다. 다른 실행이 소유 중이면 브라우저를
건드리지 않고 기다립니다.

## LOGIN_BARRIER

다음 순서를 사이트마다 수행합니다.

1. `scripts/portal_browsers.sh status`와 `cdp <site>`로 실제 endpoint를 읽습니다.
2. 실행 중인 관리 브라우저의 기존 exact target 하나를 찾습니다.
3. 대상이 없으면 새로 만들지 않습니다. `managed_browser_missing` 또는
   `exact_target_missing`으로 종료합니다. 새 창 0개, 새 탭 0개입니다.
4. `owner_activity.py`가 사람 사용 중이라고 판정하면 `HUMAN_ACTIVE`에서 무조작
   대기합니다.
5. 같은 exact target의 fresh DOM에서 사이트별 로그인 마커를 읽습니다.
6. 이미 로그인됐으면 mutation 0회로 `AUTHENTICATED`를 반환합니다.
7. 정상 로그아웃이면 검증된 exact-target 자동 로그인 어댑터만 1회 사용할 수 있습니다.
   현재 checkout에 그 어댑터가 없으면 legacy 실행기로 바꾸지 말고 다음 정식 인계로
   전환합니다.

```bash
PYTHONPATH=. python3 -m tools.multi_position_sourcing.session_guard human-auth \
  --site <site> --agent <agent> --target-id <exact-target-id>
```

8. captcha·2FA·checkpoint는 정확한 창을 한 번만 표시하고 `HUMAN_AUTH`로 전이합니다.
   사람이 처리하는 동안 click·type·navigate·reload·focus는 0회입니다.
9. LinkedIn의 multiple-sign-in 화면은 `AUTH_CONFLICT`입니다. Continue·Confirm을
   누르거나 다른 프로필에서 재로그인하지 않습니다.
10. fresh 로그인 마커와 마지막 사람 입력 후 15초 조용함을 함께 증명해야
    `AUTHENTICATED`입니다.

고정 좌표 클릭과 스크린샷 OCR 클릭은 로그인 기본 수단이 아닙니다. 검증된 실행기가
현재 DOM 요소의 사각형을 다시 읽어 클릭할 때만 허용합니다. captcha 처리나 탐지 우회,
사람처럼 위장하기 위한 임의 클릭·지연은 금지합니다. 로그인 제출은 1회이며 반복 제출하지
않습니다.

사이트별 영수증:

```json
{
  "site": "saramin|jobkorea|linkedin_rps",
  "state": "AUTHENTICATED|HUMAN_ACTIVE|HUMAN_AUTH|AUTH_CONFLICT|HANDOFF",
  "target_id": "exact target id or null",
  "proof_names": [],
  "last_verified_at": "ISO-8601",
  "browser_mutations": 0,
  "secret_fields": 0
}
```

모든 필수 사이트가 `AUTHENTICATED`일 때만 다음 영수증을 냅니다.

```text
LOGIN_BARRIER=PASS request_id=<id> sites=<comma-separated-sites>
```

하나라도 인증되지 않았으면 `LOGIN_BARRIER=BLOCKED`이며 검색은 시작하지 않습니다.

## SEARCH_EXECUTION

`LOGIN_BARRIER=PASS` 이후에만 지정된 `aisearch`, `humansearch`, `url` 스킬을 실행합니다.
검색 에이전트에는 사이트별 endpoint와 exact target id만 넘깁니다. 비밀번호·쿠키·토큰,
세션 저장값은 넘기지 않습니다.

검색 중 로그인 마커가 사라지면 해당 사이트를 `AUTH_LOST`로 바꾸고 즉시
`LOGIN_BARRIER`로 돌아갑니다. 검색 결과 0명으로 위장하거나 다른 비공식 채널로
대체하지 않습니다.

## Hook이 막았을 때

Hook 차단은 작업 포기 신호가 아닙니다. 창 종료, 새 탭, 전체 브라우저 연결, legacy
로그인 실행을 버리고 `session_guard human-auth` 정식 경로로 전환합니다. Hook을 끄거나
명령을 난독화하지 않습니다.

## 종료 보고

```text
LOGIN_BARRIER=<PASS|BLOCKED>
로그인: <site>=<state> (마커: <proof names>)
검색: <STARTED|NOT_STARTED>
브라우저 보존: 창/탭/프로필 종료 0건, CDP 연결만 해제
```
