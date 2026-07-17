# Goal 프롬프트 — 디스코드 직결 수신기 (Claude·Codex Direct Connect) v2

- 작성: 2026-07-17, 사장님 지시("2번 — Codex와 Claude가 직접 디스코드에 붙을 수 있게 적대적 검증해서 구현 프롬프팅")
- 지위: 구현 워커(Claude Code / Codex)에게 그대로 투입하는 goal 프롬프트. `docs/harness.md` 게이트 전 단계 적용.
- **검증 이력**: v1 초안 → Claude 자체 적대검증(결함 5) → Codex Rescue 2차 적대검증(추가 결함 17 + 사실오류 11 지적) → 본 v2 정정본. v1의 코드 인용 오류는 §10 정오표에 고정해 두었다 — 구현 워커는 §10을 먼저 읽고 같은 오해를 반복하지 말 것.

---

## 0. 문제 정의 (왜 만드나)

1. 현재 유일한 실경로: `Discord → Hermes 게이트웨이 → hermes_fleet_bridge → fleet_dispatch → Supabase 큐 → fleet_worker(claude -p / codex exec)`.
2. Hermes는 자체 LLM 판단 계층이 있어 (a) 좁은 규칙에 안 걸리는 문장을 자기가 처리하려다 `.claude/skills`를 못 읽고 방황하고, (b) 게이트웨이 중복 시 이중응답을 낸다(SOT30).
3. 실행자는 이미 Claude/Codex(fleet_worker의 `_run_claude`/`build_codex_exec_args`·`_run_codex`)다. **교체 대상은 접수창구뿐이다.**

## 1. 목표 (한 줄)

Hermes의 LLM 계층 없이, 우리 소유의 **얇은 디스코드 수신기**가 슬래시·텍스트 명령을 받아 **기존 해석기·권한·큐 계약을 재사용**해 잡을 넣고, 실행은 지금처럼 fleet_worker의 Claude/Codex가 한다. 수신기는 절대 스스로 실행하지 않는다.

## 2. 불변식 (절대 약화 금지 — 위반 시 즉시 FAIL)

- **INV-D1 (enqueue-only)**: 수신기는 어떤 경우에도 스스로 서치·스킬·셸을 실행하지 않는다. 파싱→권한검사→enqueue→응답뿐.
- **INV-D2 (스킬 계약)**: 검색 스킬은 기존 `FLEET_SKILLS` 그대로. 자유 지시는 **신규 스킬을 만들지 말고 기존 `OWNER_AGENT_SKILL="agent"` 계약(job_queue.py)을 재사용**한다. 발송성 스킬(jdbuilder 등) 큐 진입 금지(SOT28).
- **INV-D3 (계약 재사용·단일 파싱)**: 텍스트 명령은 `parse_hermes_fleet_args`, 권한은 `route_discord_invocation`, 등록은 `dispatch_fleet_command` 경유. 검증 로직을 수신기에 복제·완화하지 않으며, 파싱·권한검사는 경로당 정확히 1회.
- **INV-D4 (함대 전역 단일 수신기)**: 같은 봇 토큰의 수신 프로세스는 **함대 3대 전체에서 1개**. 로컬 PID 파일이 아니라 **공유 저장소(Supabase)의 원자적 임대(lease)** — 키=봇토큰 해시, 만료시각, 세대번호 — 로 강제한다. 임대 없이 기동하면 즉시 종료.
- **INV-D5 (비밀 미노출·최소권한)**: 봇 토큰·쿠키·자격증명·raw 예외문자열을 디스코드로 보내지 않는다(redact 후 요약만). **수신기는 Supabase service-role 키를 보유하지 않는다** — enqueue/조회 전용 최소권한 자격(RPC 또는 제한 키)만. 워커가 에이전트를 스폰할 때 부모 환경변수를 통째로 넘기지 말고 **화이트리스트 최소 env만** 전달.
- **INV-D6 (fail-closed)**: 신원 미확인·비인가·검증 실패 이벤트는 조용히 무시(감사 로그만). 추측 실행 금지.
- **INV-D7 (이중응답 0)**: 전환 스위치가 direct일 때 **Hermes 게이트웨이의 디스코드 수신 자체를 내린다**(플러그인 핸들러 no-op만으로는 부족 — Hermes 본체가 여전히 메시지를 받아 LLM 채팅으로 응답할 수 있음). 큐 등록 알림은 주입식 notifier로 분리해 direct 경로에서 디스패처의 직접 Discord 알림을 끈다(중복 응답 방지).

## 3. 아키텍처

```
Discord ──(gateway websocket, discord.py 버전 고정)── scripts/discord_direct_gateway.py [신규, 얇음]
              │  envelope = {event_id, user_id, platform, dm|guild,
              │              channel_id, guild_id, role_ids, command, raw_args, agent}
              ▼
tools/multi_position_sourcing/direct_receiver.py [신규, 순수로직 — 네트워크 의존 전부 주입]
   envelope → parse(기존) → authz(기존) → dispatch(기존, notifier 주입) → 응답문 생성
              ▼
기존 그대로: job_queue(Supabase) → fleet_worker(claude -p / codex exec) → 영수증 → 보고
```

- **envelope이 유일한 입구 타입**. 주의: 기존 Hermes 어댑터는 길드/채널/역할을 보존하지 않고 항상 DM으로 취급한다(`hermes_fleet_bridge.py`의 DM 고정) — 이건 재사용하지 말고 직결 수신기에서 실제 컨텍스트를 채워 기존 authz(`route_discord_invocation`)의 길드 allowlist가 처음으로 진짜로 동작하게 한다.
- **슬래시 3초 규칙**: 모든 인터랙션은 네트워크 호출(큐 등록 최대 30초) 전에 **3초 내 비공개(deferred ephemeral) 1차 응답**을 반드시 보낸다.
- **명령 소유권 일치**: 등록하는 슬래시 명령 = 디스패처가 실제 처리하는 명령만. 현재 스키마에 정의만 있고 처리 없는 명령은 등록에서 제외한다(`discord_routing.discord_slash_command_payloads` 전수 대조).
- **텍스트 명령 범위**: 기본은 owner DM + 봇 멘션만(추가 인텐트 불필요). 길드 일반 텍스트까지 받으려면 Message Content 인텐트를 개발자 포털에서 켜야 함을 문서화하고 옵션으로만.
- **등록 롤백**: `register_discord_commands.py`의 전체 PUT 교체 전에 기존 명령 payload를 파일로 백업하고, 롤백 절차(환경 복구+프로세스 종료+임대 해제+명령 재등록)를 한 묶음으로 검증.

## 4. Claude·Codex "직접 대화" 모드 (사장님 요구 핵심 — 강한 가드레일)

- 명령 `/agent-run` (텍스트 별칭 `claude: <지시>` / `codex: <지시>`), **owner 전용 + DM 한정**(OWNER_USER_IDS 하드매칭).
- 동작: 기존 `skill=agent` 잡으로 enqueue(신규 스킬 금지, INV-D2) → 워커가 `claude -p`/`codex exec` 실행 → stdout을 **redact 필터 통과 후 1,900자 분할 회신**(분할 회신은 신규 구현 — 워커의 기존 800자 절단·전송실패 무시를 이 잡 유형에서는 쓰지 않고, 전송 실패 시 재시도+실패 기록).
- 가드레일:
  - **기본 read-only 모드**: 쓰기·발송이 필요한 지시는 잡 파라미터에 명시적 승인 표식(approval_id)이 있어야 하며, 없으면 read-only 권한 모드로 실행.
  - **rate limit**: owner라도 시간당 상한. 초과분은 거부 응답.
  - **환경 격리**: 스폰 시 화이트리스트 env만(INV-D5). Discord 토큰·service-role 키는 에이전트 프로세스에 절대 미전달.
  - **발송 분리**: 이 대화 경로에서는 외부 발송(메일·InMail·제안) 불가. 발송은 SOT28 게이트 또는 사장님 명시 지시의 별도 경로로만.
  - 타임아웃은 워커 공통 계약(현재 전체 40분)을 따르고, 잡별 단축이 필요하면 워커 계약에 필드를 추가하는 정식 변경으로.
- **정보 노출 차단**: 멤버용 `fleet-status` 응답에서 owner 자유 지시문(`params.request_text` 류)·프롬프트 원문을 제외하고 job_id/machine/skill/status/시각만 반환.
- 레거시 `scripts/discord_command_listener.py`는 이 기능 검증 즉시 **실행 진입점만 격리**한다. 단, 공용 락 함수는 다른 모듈(humansearch_supabase_backfill.py)이 import하므로 별도 모듈로 분리 후 격리(임의 삭제 금지).

## 5. 작업 조각 (각 조각 = 워크트리 1개 + RED 테스트 먼저)

| 조각 | 내용 | RED 먼저 쓸 테스트(요지) |
|---|---|---|
| A | envelope 타입 + `direct_receiver.py` 순수로직(네트워크 0, notifier·queue·clock 주입) | /fleet-run→dispatch 1회·응답문; 비인가 무시; 길드 컨텍스트 보존(DM 고정 금지) |
| B | **원자적 enqueue-or-get**: `idempotency_key=discord:<event_id>` 필수 + 중복이면 기존 잡 반환(현재 DB 유니크만 있고 회수 로직 없음 — 신규 구현) | 같은 이벤트 2회→잡 1개·응답 1회; 충돌 시 raw 에러 미노출 |
| C | `discord_direct_gateway.py` — discord.py(버전 고정) 수신, 3초 deferred 응답, envelope 변환 | 인터랙션→envelope 필드 보존; 3초 내 1차 응답 호출 검증(fake) |
| D | 함대 전역 단일 임대(Supabase lease: 토큰해시·만료·세대) + 킬스위치(owner 전용 영속 정지) + 자동기동·재연결·심장박동 경보 | 동시 기동 2개 중 1개 즉시 종료; 만료 임대 회수; 정지 후 재기동 시 정지상태 존중 |
| E | `/agent-run`: skill=agent 재사용, read-only 기본, rate limit, env 화이트리스트, redact+1900자 분할 회신 | 비owner/길드 거부; 토큰 모양 마스킹; 승인 표식 없는 쓰기 지시→read-only 강제 |
| F | fleet-status 멤버 뷰 redaction + notifier 주입 분리(direct 경로에서 디스패처 직접 알림 off) | 멤버 조회에 request_text 부재; fake 큐에서 네트워크 0 |
| G | URL 검증 강화: DNS 해석 후 loopback/private/link-local/reserved/메타데이터 주소 거부(현 `_valid_url`은 userinfo만 거부 — private IP 통과됨) | 사설IP·169.254.x·localhost 도메인 거부 |
| H | 전환 스위치(`VH_DISCORD_RECEIVER=direct|hermes`) — direct 시 **Hermes 게이트웨이 수신 중지** + 명령 등록 백업/롤백 묶음 | 스위치=direct에서 Hermes 응답 0; 롤백 스크립트 왕복 검증 |
| I | 레거시 리스너 격리(락 함수 모듈 분리 포함) | backfill import 생존; 리스너 진입점 실행 불가 |
| J | 라이브 검증(§7, 승인 게이트) — **dry-run은 운영 큐와 분리된 전용 테스트 큐/머신에서만**(현 dry-run은 운영 큐 최고참 잡을 완료 처리해버리는 위험) | — |

각 조각 완료 조건: RED→GREEN, `./verify.sh` exit 0(통과 수는 **실행 시점 실측값**으로 보고 — 고정 숫자 인용 금지), 자기 적대검증 + Codex Rescue 2차 통과, `make ship` PR.

## 6. 적대 테스트 최소 목록 (조각별 RED에 반드시 포함)

1. 비인가 사용자 / 허용 안 된 길드 채널 → 무시·감사 로그(주의: 인증 연락처는 역할 없어도 허용이 현 계약 — 그 계약을 보존한 채 검사).
2. 같은 인터랙션·메시지 이벤트 2회 → 잡 1개, 응답 1회.
3. 검색 명령 인자의 따옴표·개행·U+2028·제어문자 → fail-closed. (owner 자유 지시문은 여러 줄 정상 — 개행 차단을 잘못 확대 적용하지 말 것)
4. 예외 메시지에 토큰 모양 문자열 → 회신에 원문 부재.
5. 사설IP·loopback·link-local·메타데이터 URL → 거부(조각 G 이후).
6. fake 큐에서 알림 코드 네트워크 0(notifier 주입 검증).
7. 수신기 2개 동시 기동(다른 머신 가정 포함) → 임대 못 잡은 쪽 즉시 종료.
8. `/agent-run` 비owner·길드 호출 → 무시 + 감사 로그.
9. 스위치=direct에서 Hermes로 같은 명령 → 응답 0.
10. 전송 실패 시 agent-run 회신 재시도·실패 기록(회신 유실 금지).
11. 멤버 fleet-status에 owner 지시 원문 부재.
12. env 화이트리스트: 스폰된 에이전트 환경에 DISCORD_BOT_TOKEN·service-role 키 부재.

## 7. 라이브 검증 (조각 J — 사장님 승인 후에만)

1. 스테이징: **별도 테스트 봇 토큰 + 테스트 채널 + 전용 테스트 큐**에서 `/fleet-run <테스트 URL>` → 3초 내 1차 응답 + 최종 응답 1회 + 잡 1개.
2. 전환: 명령 payload 백업 → `VH_DISCORD_RECEIVER=direct` → Hermes 수신 중지 확인 → 실채널 `/fleet-status` 1회 응답.
3. 롤백 리허설: 스위치 복귀+프로세스 종료+임대 해제+명령 재등록을 실제로 1회 왕복.
4. 증거: 응답 스크린샷, Supabase 잡 row, 워커 로그, 임대 row.

## 8. 인수 기준 (전부 충족해야 "완료")

- [ ] `/fleet-run <URL>` 1회 → 응답 정확히 1회 + 잡 정확히 1개 (3초 규칙 준수).
- [ ] §6 적대 테스트 전부 GREEN.
- [ ] `/agent-run`(owner DM)으로 Claude·Codex 각 1회 왕복, 회신에 비밀 미노출, 분할 회신 동작.
- [ ] 전환·롤백 왕복 리허설 성공, 이중응답 0 증명.
- [ ] `./verify.sh` exit 0 — 실측 통과 수를 증거로 보고.
- [ ] 레거시 리스너 진입점 격리 + backfill import 무손상.

## 9. 금지사항 (구현 워커에게)

- Hermes 코드 삭제 금지(수신 중지까지만 — 삭제는 라이브 2주 안정 후 별도 지시).
- FLEET_SKILLS 확장·SOT28 발송 게이트·캡차 개입(SOT26)·자동 재개(SOT29 INV9) 약화 금지.
- 테스트 약화·skip 금지. 단위테스트에서 discord.py 실네트워크 금지.
- `.env*`·토큰·쿠키를 코드·로그·픽스처에 복사 금지.
- 안전장치를 프롬프트 문구에만 의존시키지 말 것 — 기계적 강제(권한 모드, env 화이트리스트, redact 필터, 큐 계약)를 우선.

## 10. 정오표 (v1의 사실오류 — 같은 오해 반복 금지)

| v1 주장 | 실제 |
|---|---|
| skill="agent-chat" 신설 | 코드에 없음. 기존 `OWNER_AGENT_SKILL="agent"` 재사용 |
| `_valid_url`이 사설망 거부 | userinfo만 거부, private IP 통과 — 조각 G에서 보강 |
| Codex 실행 위치 fleet_worker.py:319 | 실제는 `build_codex_exec_args()` / `_run_codex()` (줄번호 대신 함수명 인용) |
| owner 잡 타임아웃 20분 | 워커 공통 40분, 잡별 필드 없음 |
| 워커가 1,900자 분할 회신 | 레거시 리스너 전용. 워커는 800자 절단 + 실패 무시 — 조각 E에서 신규 구현 |
| 중복 이벤트 → 기존 잡 반환이 이미 있음 | DB 유니크만 존재, 회수 로직 없음 — 조각 B에서 신규 구현 |
| Hermes가 길드/역할 envelope 보존 | 항상 DM으로 고정 — 직결 수신기가 처음으로 실컨텍스트 전달 |
| 역할 없으면 무조건 거부 | 인증 연락처는 역할 없어도 허용이 현 계약 |
| owner 프롬프트가 외부발송 전부 금지 | 실제는 "대상·채널·횟수 확대 금지"의 제한 문구 — 기계적 강제 별도 필요 |
| 개행 차단이 모든 입력에 적용 | 검색 명령 인자 한정. owner 자유 지시문은 여러 줄 정상 |
| "기존 287개 테스트 통과" 고정 인용 | 실행 시점 실측값만 증거로 인정 |
