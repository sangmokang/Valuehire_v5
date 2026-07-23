# Discord 검색 즉답·로그인 선행 계약 (2026-07-23)

## 1. 목표

Discord의 `aisearch`, `humansearch`, `url`, `login` 요청은 큐나 Supabase 응답을
기다리지 않고 즉시 접수 표시를 보여 준다. `aisearch`, `humansearch`, `url`의 실제
스킬 실행은 필요한 포털의 로그인 준비 검사를 가장 먼저 실행하고, 유효한 로그인
영수증을 확인한 뒤에만 시작한다.

## 2. 인수 기준

1. 슬래시 네 명령은 `defer` 직후, 큐 접근 전에 같은 무정보 접수 표시를 보낸다.
2. 텍스트 검색 명령은 권한 확인 뒤, 큐 접근 전에 접수 표시를 보낸다.
3. 검색 잡의 로그인 영수증이 없거나 만료됐으면 정식 `portal_login` 준비 러너를
   한 번 실행하고 영수증을 다시 검사한다.
4. 자동 로그인으로 영수증이 준비되면 같은 잡의 검색 러너를 계속 실행한다.
5. 캡차·2FA·checkpoint 등으로 준비되지 않으면 검색 러너를 실행하지 않고
   `paused_for_human`으로 둔다.
6. 주입 러너를 쓰는 기존 단위테스트·시뮬레이션 계약은 바꾸지 않는다.

## 3. 비범위

- Discord/Supabase 운영 배포와 봇 재시작
- 라이브 채용 사이트 검색
- 캡차·2FA·checkpoint 자동 우회
- 새 브라우저 창·탭 생성 정책 변경
- Hermes 종료 단계 변경

## 4. 검증

- `python3 -m pytest -q tests/test_discord_direct_gateway.py tests/test_discord_bot_safety_gates.py`
- `python3 skills/ai-search/scripts/ai_search_sot_check.py --repo .`
- `python3 skills/disearch/scripts/audit_disearch.py --repo .`
- `./verify.sh`
