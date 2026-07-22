# Goal 프롬프트 — 디스코드 직결 게이트웨이 조각 D (함대 전역 단일 임대 + 킬스위치 + 자동재연결)

- 작성: 2026-07-21, 조각 C(`discord_direct_gateway.py`, PR#153) 병합 완료 직후 이어서.
- 지위: 구현 워커(Claude Code / Codex)에게 그대로 투입하는 goal 프롬프트. `docs/harness.md` 게이트 전 단계 적용.
- 정본 스펙: `docs/prompts/discord-direct-connect-goal-2026-07-17.md` §5 표의 **"조각 D" 행**이 이번 작업 범위다. INV-D4(§2)·§6 적대 테스트 7번을 그대로 만족해야 한다. 아래는 그 문서 + 조각 C verdict(`docs/engineering/discord-direct-gateway.verdict.json`)의 known_limitations 를 종합한 실행 프롬프트지 원문 대체가 아니다 — 반드시 두 문서를 먼저 읽어라.

## 0. 왜 지금 이 조각인가

조각 C(`scripts/discord_direct_gateway.py`)가 이미 병합됐다. 그 verdict 문서 known_limitations 에 사장님이 명시적으로 박아둔 문장:

> "이 조각(C)이 병합되는 시점에는 함대 전역 단일 임대(조각 D, Supabase lease 로 동시 기동 방지)가 아직 없다 — 로컬에서 여러 인스턴스를 동시에 띄우면 같은 Discord 이벤트에 중복 응답이 날 수 있다. 조각 D 배송 전까지는 게이트웨이 프로세스를 항상 1개만 수동으로 기동해야 한다."

이 한계를 없애는 것이 조각 D의 유일한 목적이다. 새 기능을 얹지 말고 정확히 이 구멍만 막는다.

## 1. 목표 (한 줄)

`scripts/discord_direct_gateway.py` 기동 시 Supabase에 원자적 임대(lease)를 잡지 못하면 **즉시 종료**하게 만들어, 함대 3대(맥미니·맥북·윈PC) 중 같은 봇 토큰으로 동시에 뜬 인스턴스가 2개 이상이면 1개만 살아남게 한다. 더불어 owner 전용 영구 킬스위치와 재연결·심장박동 경보를 붙인다.

## 2. 불변식 (goal §2 INV-D4 그대로 — 절대 약화 금지)

> **INV-D4 (함대 전역 단일 수신기)**: 같은 봇 토큰의 수신 프로세스는 함대 3대 전체에서 1개. 로컬 PID 파일이 아니라 **공유 저장소(Supabase)의 원자적 임대(lease)** — 키=봇토큰 해시, 만료시각, 세대번호 — 로 강제한다. 임대 없이 기동하면 즉시 종료.

추가로 이번 조각이 반드시 지킬 것(조각 C에서 이미 확립된 계약과 일관):

- **INV-D5 연장(비밀 미노출·최소권한)**: 조각 C가 이미 `DISCORD_GATEWAY_SUPABASE_URL/KEY`(anon 급 최소권한)만 쓰고 service-role 키를 게이트웨이 프로세스에 두지 않는 계약을 만들어 놨다(`scripts/discord_direct_gateway.py` 의 `MinimalPrivilegeQueueClient` / `_build_client` 참고, 조각 C 커밋 `229454b`). **조각 D의 lease·killswitch RPC도 같은 anon 최소권한 키로만 호출 가능해야 한다** — service-role 폴백 추가 금지, 실패 시 fail-closed(SystemExit).
- **봇 토큰 해시**: lease 테이블의 키는 봇 토큰 원문이 아니라 해시(예: sha256)여야 한다(INV-D5, 토큰 원문을 DB/로그에 남기지 않음).
- **킬스위치는 owner 전용 영속 정지**: `fleet_account_pause_barrier`(2026-07-15) 패턴처럼 시간 만료 없이 수동 해제를 기다리는 서버측 장벽으로 만든다. 단, 그건 "계정 잠금"이고 이건 "게이트웨이 전체 기동 금지" — 다른 개념이니 새 테이블/함수로 분리하되 같은 안전 철학(자동 보정 없이 명시적 owner 해제만)을 따른다.
- **심장박동**: 기존 `machine_heartbeats`/`record_heartbeat`/`heartbeats_epoch`(2026-07-11) 는 "머신"단위다. 이번 lease는 "봇토큰(수신 프로세스)"단위라 별개 개념 — 기존 테이블을 억지로 재사용해 의미를 흐리지 말고, 재사용 가능한 부분(epoch 반환 방식, RLS/grant 패턴)만 스타일로 따라간다.

## 3. 작업 범위 (이번 조각만 — 다른 조각 손대지 말 것)

1. **Supabase 마이그레이션**(신규 파일, `supabase/migrations/2026072x_discord_gateway_lease.sql`):
   - `discord_gateway_leases` 테이블: `token_hash text primary key`, `holder_machine text`, `holder_pid integer`, `generation bigint`, `acquired_at timestamptz`, `expires_at timestamptz`, `released_at timestamptz null`.
   - `discord_gateway_killswitch` 테이블(싱글턴 또는 `token_hash` 키): `engaged boolean`, `engaged_by text`(owner discord user_id), `engaged_at timestamptz`, `note text`.
   - RLS + `revoke all from public, anon, authenticated` + 필요한 함수만 `grant execute ... to anon`(조각 C의 `MinimalPrivilegeQueueClient` 가 anon 키를 쓰므로 — 이미 있는 20260719 마이그레이션의 grant 패턴을 그대로 따라간다. service_role 은 여기서 grant하지 않는다. anon RPC 는 반드시 파라미터 검증 + `security definer` 로 인가 우회 없게 짠다 — 조각 C 4~5차 Codex 재검증에서 "anon RPC 인가우회"가 CRITICAL로 걸렸던 사례를 반복하지 말 것, 같은 계열 실수를 자기 적대검증에서 먼저 찾아라).
   - `acquire_or_renew_gateway_lease(p_token_hash text, p_machine text, p_pid integer, p_ttl_seconds integer)` — 원자적: 기존 임대가 없거나 만료됐으면 새 세대로 획득, 살아있는 다른 홀더가 있으면 실패(자기 자신의 갱신은 성공). 반환에 `acquired boolean, generation bigint, holder_machine text` 등 판정에 필요한 값 포함.
   - `release_gateway_lease(p_token_hash text, p_machine text, p_generation bigint)` — 정상 종료 시 반납(선택 구현이지만 있으면 재기동이 빠름 — TTL 만료로도 결국 회수되니 필수는 아님, 있으면 좋음).
   - `is_gateway_killswitch_engaged(p_token_hash text)` — killswitch 조회.
   - `engage/release_gateway_killswitch(...)` — owner 전용 조작. **주의**: 이 RPC들은 discord 게이트웨이 프로세스가 아니라 `/agent-run`류 owner 명령 경로 또는 별도 운영 스크립트에서 호출될 수 있다 — 인가(owner_id 검증)를 **DB 함수 안에서 다시 강제**할지, 호출부(파이썬)에서만 강제할지 설계 판단을 내리고 근거를 verdict에 남겨라(조각 C가 "anon RPC 는 파라미터만 보고 신원을 못 믿는다"는 교훈을 남겼다 — 이 함수들도 같은 함정에 빠지지 않게).

2. **`scripts/discord_direct_gateway.py` 배선**:
   - 기동 시(`setup_hook` 또는 `main()` 진입부) `acquire_or_renew_gateway_lease` 호출 → 실패하면 로그 남기고 **즉시 `SystemExit`**(§6 적대 테스트 7번: "동시 기동 2개 중 1개 즉시 종료").
   - 주기적 갱신 태스크(예: TTL의 절반 주기로 `discord.ext.tasks.loop` 또는 `asyncio` 백그라운드 태스크) — 갱신 실패(다른 홀더가 뺏어감/DB 오류)가 반복되면 자기 자신도 종료해야 한다(임대 없이 계속 도는 상태 금지).
   - 기동 직후 + 주기적으로 killswitch 확인 — 걸려 있으면 접속하지 않고/접속 중이면 정상 종료. "정지 후 재기동 시 정지상태 존중"(§5 RED 요지) — 재시작해도 killswitch가 안 풀렸으면 다시 종료해야 한다.
   - **자동재연결**: discord.py 자체 재연결(라이브러리 기본 동작)에 얹혀가되, 재연결마다 새로 lease를 뺏길 필요는 없다(같은 프로세스가 살아있는 채 네트워크만 끊긴 경우와, 프로세스 자체가 죽고 다른 머신이 뜨는 경우를 구분 — 세대번호가 이 구분의 핵심).
   - **심장박동 경보**: 임대 갱신 실패나 killswitch 감지 시 조용히 죽지만 말고 감사로그(조각 C의 `_default_audit` 계열)에 남긴다. 알림 자체가 봇처럼 사람을 스팸하지 않게 — 실패 1회로 경보 남발 금지, 지속 실패(예: N회 연속)만 경보로 승격.

3. **환경변수**: `DISCORD_GATEWAY_LEASE_TTL_SECONDS`(기본값 명시, 너무 짧으면 네트워크 지연에 오탐, 너무 길면 장애 전환 느림 — 60~120초대 권장하되 근거를 verdict에 남겨라), 봇 토큰 해시는 기존 `DISCORD_BOT_TOKEN` 값을 코드 내부에서 해시만 해서 쓴다(env 신규 추가 불필요).

## 4. RED 테스트 요지 (§5 조각 D 행 + §6 적대 테스트 7번, 그대로)

1. **동시 기동 2개 중 1개 즉시 종료**: fake Supabase RPC(두 "머신" 역할의 클라이언트가 거의 동시에 `acquire_or_renew_gateway_lease` 호출)로 시뮬레이션 — 실제 discord.py/네트워크 없이 게이트웨이의 "임대 실패 시 SystemExit" 로직만 단위테스트로 검증(단위테스트 실네트워크 금지, goal §9).
2. **만료 임대 회수**: 임대가 TTL을 넘겨 죽은 상태를 가정한 fake에서 새 홀더가 새 세대로 획득 가능함을 검증.
3. **정지 후 재기동 시 정지상태 존중**: killswitch engaged 상태에서 게이트웨이를 (재)기동하면 lease 획득 성공 여부와 무관하게 접속하지 않고 종료.
4. 갱신 실패 반복 시 자기 종료(라이브러리 자체 재연결에 기대 무한정 "임대 없이 떠 있는" 상태로 남지 않는지).
5. lease/killswitch RPC 호출에 service-role 키가 필요 없음을 코드/설정 레벨로 재확인(조각 C의 "서비스롤 키 미보유" 트립와이어 패턴을 그대로 확장).
6. 토큰 해시가 원문 토큰을 노출하지 않음(DB row·로그·예외 메시지 어디에도 원문 토큰 부재).

## 5. Harness 절차 (조각 C와 동일하게 — 게이트 건너뛰지 말 것)

0. `make red-ledger` 로 시작 자격 확인.
1. `make task NAME=discord-gateway-lease` (또는 저장소 관행상 `Valuehire_v5-discord-gateway-lease` 워크트리)로 워크트리 생성. 이후 전부 그 안에서만.
2. RED: `tests/test_discord_gateway_lease.py`(신규) 작성 → 실패 확인 → 커밋.
3. GREEN: 마이그레이션 SQL + `scripts/discord_direct_gateway.py` 배선 최소 구현.
4. `./verify.sh` exit 0, 실측 통과 수 그대로 보고.
5. 스스로 적대검증(뮤턴트로 각 RED 항목 무너뜨려 테스트가 잡는지 확인, 원복).
6. `codex:codex-rescue` 서브에이전트로 2차 독립 적대검증. 조각 C 사례처럼 라운드가 여러 번(3~5회) 걸릴 수 있음 — 수렴할 때까지 반복.
7. `docs/engineering/discord-gateway-lease.verdict.json` 작성(조각 C verdict 형식 그대로 참고, known_limitations 섹션에 "마이그레이션이 라이브 Supabase에 자동 적용되지 않음"(조각 C와 동일한 배포 갭)을 이번에도 명시).
8. `make ship` 으로 push+PR(merge는 하지 말 것 — 사장님 확인 후 병합).

## 6. 금지사항 (goal §9 + 조각 C에서 얻은 교훈)

- service-role 키를 게이트웨이/lease RPC 경로에 절대 넣지 않는다.
- 봇 토큰 원문을 DB/로그/예외 메시지/커밋에 남기지 않는다.
- 단위테스트에서 discord.py 실네트워크·실제 Supabase 접속 금지(전부 fake 주입).
- FLEET_SKILLS 확장 금지, SOT28 발송 게이트 약화 금지.
- anon RPC 함수를 만들 때 "파라미터만 믿고 신원을 안 믿는" 조각 C의 실수(4~5차 Codex 재검증 CRITICAL)를 반복하지 말 것 — 특히 killswitch engage/release 는 owner 검증 위치를 명확히 하고 근거를 남겨라.
- 조각 C가 이미 병합해놓은 `MinimalPrivilegeQueueClient`/`slash_commands_to_register`/3초 defer 로직을 재구현하지 말고 그대로 재사용.
