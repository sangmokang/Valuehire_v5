# humansearch 브라우저 환경 전수 조사 선행 — goal

## 현재 상태

- `skills/humansearch/SKILL.md`의 시작 게이트는 SOT·설정·메모리 회수를 요구하지만,
  브라우저를 열거나 CDP에 붙기 전에 실행 중인 포트·프로필·탭을 전수 조사하라는
  기계적 계약이 없다.
- `scripts/portal_browsers.sh cdp <channel>`은 채널별 실제 포트를 해석할 수 있으나,
  전수 조사 없이 고정 포트 상태를 먼저 확인하면 사람인·링크드인 창을 오판할 수 있다.

## 인수 기준

humansearch 스킬과 계약 테스트가 다음을 명시해야 한다.

1. 브라우저 조작 전에 모든 실행 중 디버그 크롬의 실제 CDP 포트와 `--user-data-dir`를 조사한다.
2. 각 CDP 엔드포인트의 `/json/list`에서 페이지 URL·타입·제목·로그인/캡차/멀티세션 신호를 수집한다.
3. 조사 결과를 한국어로 보고하고, 상태가 확인되기 전에는 `start`, `navigate`, `attach`, 검색,
   프로필 순회를 실행하지 않는다.
4. 조사 후에도 사용자가 지정한 채널만 조작하며, 실제 포트는 프로필 헬퍼로 재해석한다.

## 비범위

브라우저를 자동으로 시작·종료하거나 로그인·캡차를 우회하는 동작은 추가하지 않는다.

## 검증

```bash
pytest -q tests/test_humansearch_skill.py
python3 "$HOME/.codex/skills/skill-creator/scripts/quick_validate.py" "$HOME/.codex/skills/humansearch"
```
