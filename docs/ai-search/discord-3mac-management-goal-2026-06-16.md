# Goal Prompt — 디스코드로 맥 3대 관리: 실현성 + 시뮬레이션 검증

작성일: 2026-06-16 · 모드: strict · 대상: harness 게이트로 실행하는 코딩 에이전트
형제 문서: `three-mac-leader-control-plane-goal-2026-06-16.md`(전송선 비교), `three-mac-account-coordinator-goal-prompt.md`(계정 자물쇠)
검증: 코드 직접 인용 + Codex 2패스 적대검증 + Claude 재현(이중검증)

---

## 0. 한 줄 목적

**디스코드 한 줄로 맥 3대를 "관리"하는 게 실제로 되는지**를 — 진짜 디스코드·진짜 맥 없이
**인메모리 시뮬레이션**으로 먼저 증명한다. 시뮬레이션이 통과해야 실제 배선으로 간다.

> ⚠️ 이 문서는 설계+시뮬 검증 스펙이다. 실제 구현은 `docs/harness.md` 게이트(과거회수 → 인수기준1 →
> RED → 작은단위 → ./verify.sh → 2패스 적대검증 → ship)로 슬라이스별. 한 슬라이스 = 워크트리 1개.

---

## 1. 실현성 판정 (코드 직접 확인)

### 이미 있는 것 (재사용 — 새로 만들지 않음)
- **명령 해석**: `discord_routing.py:95 parse_discord_command_text` — `/run-search source:saramin keyword:...` 파싱.
- **허가 체크**: `discord_routing.py:146 route_discord_invocation` + `:73 load_discord_access_config` — user/channel/role allowlist. DM·서버채널 구분(`:138`).
- **지원 명령 5종**: `discord_routing.py:13` — `search-status, run-search, register-position, session-status, relogin-needed`.
- **슬래시명령 등록**: `register_discord_commands.py:30 bulk_register_discord_commands`(Discord API PUT).
- **결과 알림 전송**: `portal_ops.py:301 DiscordWebhookNotifier`(POST webhook). **`urlopen` 주입 가능(:304) → 시뮬에서 가짜로 대체 가능.**

### 없는 것 (빈 자리 = 이번 작업)
- **수신("듣는 귀")**: 디스코드가 보낸 슬래시 명령을 받는 엔드포인트(Interactions webhook 또는 봇 게이트웨이)가 **부재**. `rg gateway|websocket|on_message|listen|interaction tools/` → **0건**.
- **3대 배분("나눠주는 손")**: 들은 명령을 3대 중 누가 할지 정하는 배분기 부재.
- **원자적 집기(claim)**: 두 맥이 같은 명령을 동시에 집어도 1대만 실행하는 장치 부재(`portal_worker.py:203` flock은 로컬 전용).

### 판정
**디스코드로 3대 관리는 "가능하나 단독으로는 위험".** 디스코드는 브로드캐스트 채널이라 한 명령을 3대가 다 본다 →
정밀 배정·중복방지를 디스코드만으로 하면 race·rate limit·순서꼬임이 난다. **안전형 = 하이브리드:**

```
사장님(폰) ──/run-search…──▶ 디스코드 채널
                               │ (수신 엔드포인트 = 새로 만들 "귀")
                               ▼
                     parse + route (이미 있음, 허가 통과만)
                               │ 허가 OK면
                               ▼
                     중앙 작업판(Supabase task_queue)에 task 1건 적재  ◀── 디스코드는 여기까지
                          ▲ claim        ▲ claim
                    [맥북]            [맥에어]   ← 큐에서 원자적으로 1대만 집어 로컬 실행
                          │ 결과            │ 결과
                          ▼                ▼
                     DiscordWebhookNotifier로 결과 알림(멱등, 단일 발신)
```

**핵심: 디스코드 = "주문 받는 카운터 + 결과 알림판". 실제 3대 배분은 중앙 작업판(큐)이 한다.**
디스코드가 직접 3대에게 명령을 쏘지 않음 → rate limit·race 회피.

---

## 2. 시뮬레이션 설계 (이번 goal의 핵심 — 진짜 디스코드 없이 증명)

순수 파이썬(numpy 금지, CI 제약)으로 **인메모리 하니스**를 만든다. 외부 네트워크 0.

### 구성요소 (전부 가짜·결정론)
1. **FakeDiscord**: 슬래시명령 시퀀스를 리스트로 주입(예: 허가된 명령 5 + 허가안된 명령 2 + 중복 명령 3). 실제 `parse_discord_command_text`/`route_discord_invocation`를 **그대로 호출**(이미 있는 코드 검증).
2. **FakeTaskQueue**: dict/list 기반. `claim(worker_id)`는 단일 임계영역에서 status pending→claimed CAS(테스트 락). 멱등키(command+options+time_window)로 중복 적재 차단.
3. **FakeWorker ×3**(맥북/미니/에어): 큐 폴링 → claim → "실행"(가짜, 카운터 증가) → 결과를 FakeNotifier로. 한 워커는 "claim 후 멈춤(잠자기)" 시킬 수 있어야 함(페일오버 시뮬).
4. **FakeNotifier**: `DiscordWebhookNotifier`에 **가짜 `urlopen` 주입**(`portal_ops.py:304`) → 실제 전송 0, 호출만 기록.
5. **결정론 시계**: 주입 가능한 fake clock(429 백오프·TTL 만료 시뮬).

### 검증 단언 = 인수 기준 (각 단언 = 워크트리 1개)

- **S1 — 허가 게이트**: 허가 안 된 user/channel 명령은 **task 적재 0, 실행 0**. (재사용: `route_discord_invocation`)
- **S2 — 중복 명령 멱등**: 같은 `/run-search source:saramin keyword:X`를 3번 보내도 같은 시간창에서 **task 1건만** 적재.
- **S3 — 원자적 집기**: 3 워커가 같은 task를 동시에 claim 시도 → **정확히 1대만 실행**(중복 0).
- **S4 — 페일오버**: claim한 워커가 멈춤 → TTL 만료 → 다른 워커 인수. 최종 **실행 1회**(중복도 유실도 0).
- **S5 — rate limit 백오프**: FakeDiscord/Notifier가 429 반환 → **백오프 후 재시도, 명령/알림 유실 0**.
- **S6 — 알림 멱등**: 한 task 완료 결과 webhook은 **정확히 1회**(3대가 동시 완료 보고해도 중복 알림 0).
- **S7 — 보호계정 동시성**: 같은 보호계정(saramin) task 2건이 서로 다른 워커에 잡혀도, **계정 자물쇠(형제문서) 경유로 동시 실행 0**. (자물쇠 미구현이면 이 슬라이스는 형제문서 Slice 1 선결로 표시)

### 시뮬 산출물
- `artifacts/discord-3mac-sim/` 아래에 실행 로그(JSON): 보낸 명령 수 / 적재 task 수 / 실행 수 / 중복 수 / 유실 수 / 알림 수. **사람이 읽는 요약표**도 함께. 비밀값 출력 금지.

---

## 3. 슬라이스 순서 (위험·의존 순)

> 선결: 보호계정 동시실행(S7)은 형제문서 Slice 1(계정 자물쇠) 없이는 미보장 — 그 전엔 S7을 "공개웹 채널"로만 시뮬.

- **D1 — 시뮬 하니스 + S1/S2/S3**: FakeDiscord/Queue/Worker/Notifier + 허가·멱등·원자집기 단언. RED: 3 워커 동시 claim에 2대 실행되는 실패 테스트 먼저.
- **D2 — S4/S5/S6**: 페일오버·백오프·알림멱등.
- **D3 — 수신 엔드포인트("귀")**: 실제 Discord Interactions 수신부(서명검증 포함) — 단, **명령은 큐 적재까지만**(실행은 워커가). RED: 서명 위조 요청 거부.
- **D4 — 워커 폴링 러너**: 실제 큐에서 claim→로컬 실행→결과 알림. 발송은 사람(SOT).
- **D5 — 보호계정 자물쇠 결합(S7)**: 형제문서 Slice 1 위에 얹어 같은 계정 2대 동시 0.

---

## 4. SOT 체크리스트 (절대 약화 금지)

- [ ] 3사 자동로그인 안 막음(보안문자/2FA/checkpoint는 사람에게 — 자동우회 금지)
- [ ] 발송(제안·메일·InMail)은 **항상 사람이 마지막 클릭** — 디스코드 명령으로 자동발송 금지(`run-search`는 검색 큐 적재까지만)
- [ ] service-role 키·포털 비밀번호는 **허브(미니)에만**. 팔로워는 scoped role로 task poll/claim/heartbeat만
- [ ] admin/디스코드엔 요약·점수·근거URL·공개링크까지만(이력서 원문·OCR·연락처 원본 금지)
- [ ] 보호계정 한 번에 한 대(S7, 계정 자물쇠 경유)
- [ ] 디스코드 수신 엔드포인트를 공개 인터넷에 무방비 노출 금지(서명검증 필수)
- [ ] 보고는 쉬운 한국어

> 참고: R4(크롬 쓰면 그 맥 정지)는 2026-06-16 SOT에서 삭제됨(메모리 `r4-removed-linkedin-cdp-exception`).
> 자동 크롬은 전용 프로필로 사장님 크롬과 분리 전제. 링크드인 RPS만 CDP 9222 충돌 예외 — 운영 중 사장님이 직접 피함.

## 5. 비범위
- 디스코드를 **기계↔기계 정밀 작업버스**로 쓰기 — 안 함(브로드캐스트·race·rate limit). 큐가 배분.
- 자동 발송 — 영구 비범위(SOT).
- 새 메시지 브로커 도입 — 안 함. 이미 있는 Supabase + 디스코드 재사용.

## 6. 검증 (게이트 4a)
```bash
./verify.sh                                              # exit 0, 출력 숫자 그대로 보고
python3 -m unittest tests/test_discord_3mac_sim.py -v    # 시뮬 단언 S1~S6(S7은 자물쇠 후)
```

---

## 적대 검증 로그 (2026-06-16 · strict 2패스 + 이중검증)
> 패스1=Claude 직접, 패스2=Codex 독립, 그 뒤 Claude가 Codex 증거 재현. 본문 그대로 보존.
> (codex:rescue 실행 후 본문/agentId/verdict 파일 경로와 함께 append)
