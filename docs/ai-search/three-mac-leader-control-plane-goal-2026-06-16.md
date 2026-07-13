# Goal — 맥 3대 "리더가 지휘하는" 제어 평면 (Leader Control Plane)

작성일: 2026-06-16 · 대상: harness 게이트로 실행하는 코딩 에이전트 · 모드: strict
형제 문서: `docs/ai-search/three-mac-account-coordinator-goal-prompt.md`(상호배제 자물쇠)
검증: 코드 직접 인용 + Codex 2패스 적대검증 + Claude 재현(이중검증)

---

## 0. 한 줄 목적

맥 3대 중 **한 대(리더 = 허브, Mac mini)** 가 나머지 맥에게 **"무슨 일을 해라"를 배정·지휘**하고,
각 맥은 **자기 안에서 그 일을 직접 실행**한 뒤 결과를 중앙에 돌려준다.
**리더가 남의 맥 키보드/브라우저를 원격조종(puppet)하는 게 아니라, "할 일(task)"만 배정한다.**

> ⚠️ 이 문서는 **방법론 설계 검토**다(코드 아님). 실제 구현은 `docs/harness.md` 게이트
> (과거회수 → 인수기준1개 → RED → 작은단위 → ./verify.sh → 2패스 적대검증 → ship)로 슬라이스별 진행.

---

## 1. 먼저: 두 개의 다른 축을 분리한다 (가장 중요)

사장님 질문("한 대가 제어")은 두 뜻이 섞일 수 있다. **반드시 ①로 한다.**

| 축 | 뜻 | 판정 |
|---|---|---|
| ① **작업 오케스트레이션** | 리더가 *무엇을(어느 포지션/채널)* 누가 할지 배정. 실행은 각 맥이 **로컬에서** | ✅ **이걸로 한다** |
| ② **원격 조종(puppet)** | 리더가 남의 맥의 마우스/키보드/브라우저를 네트워크로 직접 운전(VNC/RPA) | ❌ **하지 않는다** |

**왜 ②를 버리나:** 각 맥엔 이미 자기 크롬·세션·Playwright 러너가 있다(`portal_worker.py:501` 로컬 브라우저 기동).
남의 맥 브라우저를 네트워크로 원격운전하면 — 지연·끊김·세션충돌로 깨지기 쉽고, SOT R4(사장님이 그 맥 크롬 쓰면 즉시 양보)와도 정면충돌한다.
**올바른 모델: 리더는 "할 일"을 큐에 넣고, 일하는 맥이 깨어있고 한가할 때 스스로 가져가 자기 브라우저로 실행한다.**

---

## 2. 현재 상태 (코드 직접 확인 — 증거)

- 각 맥은 **독립 launchd 루프**로 돈다: `scripts/valuehire-search-loop.sh:11-26`(`while true; dry_run; sleep 900`), `scripts/launchd/com.valuehire.search-runner.plist`. **리더·배정 없음 — 3대가 똑같은 일을 눈치없이 반복할 수 있음.**
- 큐는 **한 기기 안**에서만: `queue_runner.py:47 plan_queue_cycle`/`:143 run_live_queue_cycle`(pending/resume, CDP끊김 시 pending 보존). **크로스머신 배정 없음.**
- 잠금은 **로컬 전용**: `portal_worker.py:203-214` flock(한 컴퓨터 안 직렬화만).
- Hermes = **로컬 명령 실행 게이트**: `tools/hermes-agent/valuehire/vh-codex-dispatch.mjs:1-40`(기본 dry-run, `OWNER_SIGNOFF_CODEX_EXEC=approved`라야 write, 샌드박스 강등+env 세탁). **전송선 아님 — 실행측 안전 게이트.**
- 디스코드 = **사람→시스템** 명령: `discord_routing.py:95 parse_discord_command_text`/`:146 route_discord_invocation`/`:73 load_discord_access_config`(허가 user/channel ID). **기계↔기계 배정 아님.**
- 중앙 상태저장소는 있음: `docs/ai-search/session-state-supabase-schema-2026-06-09.sql`(단, service-role 전용 — `portal_live_check.py:937-948`가 `SUPABASE_SERVICE_ROLE_KEY` 강제).

**결론: 리더 제어 평면은 부재. 단, 재사용할 씨앗(Supabase 중앙저장소·queue_runner·Hermes 게이트·디스코드 허가체크)은 이미 있음.**

---

## 3. 방법론 비교 (리더 → 팔로워 전송선)

| 방법 | 모델 | 장점 | 단점/위험 | 적합도 |
|---|---|---|---|---|
| **A. Supabase 작업 큐 (pull)** | 리더가 task 행 INSERT → 팔로워가 폴링·원자적 claim(CAS)·로컬 실행·결과 write-back | NAT/방화벽 무관(아웃바운드만), 잠자기·로밍·끊김에 강함, **이미 있는 중앙저장소+코디네이터 리스 재사용**, R4가 자연스러움(한가할 때만 폴링) | 폴링 지연(수초~수십초), claim 원자성 꼭 필요 | ⭐ **주(主)** |
| **B. SSH push** | 리더가 `ssh 팔로워 '...'` 직접 실행 | 즉시성, 단순 | 팔로워 인바운드 SSH 필요, 노트북 잠자기/IP변동에 깨짐, VPN(Tailscale) 필요, 리더가 팔로워 상태를 모름 | 보조(수동 점검용) |
| **C. 디스코드 명령버스** | 리더/사람이 채널에 명령 → 팔로워 구독·실행 | 사람도 같은 채널로 지휘, **허가체크 재사용**(`discord_routing.py:73`) | rate limit·순서보장 약함, 기계↔기계 전송엔 부적합, 단일발신자 규칙과 충돌 가능 | **사람 지휘/알림 채널**로만 |
| **D. Claude Code 헤드리스 실행기** | 전송과 무관 — 팔로워가 `claude -p`(Max 0원) 또는 `python -m queue_runner`로 **실제 일을 함** | LLM 판단 필요한 일에 강함, 토큰 0원, 영속화 | 전송선 아님(A/B/C 위에 얹는 "손") | **실행기**(A와 결합) |
| **E. Hermes 실행 게이트** | 팔로워가 claim한 일을 Hermes 서명게이트로 안전 실행 | 샌드박스·서명·env세탁 **이미 구현** | 전송선 아님(실행측 가드) | **쓰기/발송 가드**(A와 결합) |

---

## 4. 권고 아키텍처 (조합)

```
        [ 리더 = Mac mini (허브) ]
        - 키·service-role은 여기에만 (SOT)
        - 포지션 → task 분해 → Supabase task_queue INSERT
        - 계정 리스(형제 문서) 보유자에게만 보호계정 task 배정
                 │ (아웃바운드 write)
                 ▼
        ┌──────── Supabase ────────┐
        │ task_queue (pull)        │  ← 원자적 claim(CAS)+소유토큰
        │ account_lease (형제문서) │  ← 한 계정 한 대
        │ quota_ledger (형제문서)  │  ← 합산 한도
        └──────────────────────────┘
            ▲ claim        ▲ claim
   (아웃바운드 폴링)   (아웃바운드 폴링)
   [ 맥북=링크드인 ]   [ 맥에어=대기/공개웹 ]
   - 한가+깨어있을 때만 폴링(R4)
   - claim → 로컬 실행:
       · 검색/수집 = python queue_runner (자기 브라우저)
       · 판단필요 = claude -p (0원)
   - 쓰기/발송 = Hermes 서명게이트 + 사람 최종클릭(SOT3)
   - 결과·하트비트 write-back
```

- **전송 = A(Supabase pull 큐).** 푸시 아닌 풀이라 잠자기·NAT·R4에 강함.
- **실행 = D(claude -p) / python 러너**, 각 맥 **로컬 브라우저**로. 원격조종 안 함.
- **안전게이트 = E(Hermes 서명) + 발송은 사람(SOT3).**
- **상호배제 = 형제 문서의 account_lease**(리더는 리스 보유자에게만 보호계정 task 배정 → 같은 계정 2대 동시 원천차단).
- **사람 지휘·알림 = C(디스코드)**, 단 **단일 발신자(미니만)**.

---

## 5. 인수 기준 (슬라이스 = 워크트리 1개씩, 큰덩어리 금지)

> 선결: 형제 문서 Slice 0(링크드인 자동로그인 모순)·Slice 1(account_lease)·자격증명 RLS 모델이 **먼저** 서야 보호계정 배정 가능.

- **L1 — task_queue 스키마 + 원자적 claim:** 두 팔로워가 같은 task를 동시에 claim하면 **한쪽만 성공**(서버시간 CAS+소유토큰). RED: 동시 claim 경합 1건만 성공.
- **L2 — 팔로워 폴링 러너(pull):** 팔로워가 한가+깨어있을 때만 폴링, claim→로컬 실행→결과 write-back→하트비트. R4 감지 시 **즉시 폴링중단 + 미완 task는 pending 반납**. RED: R4 ON이면 새 claim 0, 보유 task pending 반납.
- **L3 — 리더 배정기:** 포지션을 채널/계정별 task로 분해, **account_lease 보유 기기에만** 보호계정 task 배정, 중복 배정 0(멱등키). RED: 같은 (포지션,채널,시간창) 두 번 배정해도 task 1건.
- **L4 — Hermes 서명게이트 결합:** 팔로워의 쓰기/등록 동작은 Hermes 게이트 경유(서명 없으면 dry-run). 발송은 사람. RED: 서명 없는 write task는 실제 전송 0(dry-run 증거).
- **L5 — 리더 페일오버:** 미니(리더) 강제종료 → 에어가 **리더 역할 인수**(리더 리스), task 배정 계속, 옛 리더 좀비 배정 거부. RED: 리더 kill 후 인수 성공 + 옛 리더 토큰 배정 거부.

---

## 6. SOT 체크리스트 (절대 약화 금지)

- [ ] 3사 자동로그인 안 막음 (보안문자/2FA/checkpoint는 사람에게 — 자동우회 금지)
- [ ] R4: 사장님 크롬 보이면 그 맥 폴링·작업 즉시 중단 + 리스/task 반납
- [ ] 발송(제안·메일·InMail)은 **항상 사람이 마지막 클릭** — 리더가 자동발송 배정 금지
- [ ] service-role 키·포털 비밀번호는 **리더(미니)에만**. 팔로워는 scoped role로 task/lease/heartbeat만
- [ ] admin/디스코드엔 요약·점수·근거URL·공개링크까지만 (이력서 원문·OCR·연락처 원본 금지)
- [ ] 보호계정 한 번에 한 대 (account_lease 경유 배정)
- [ ] 보고는 쉬운 한국어

## 6.5 비상 운영면 (break-glass) — Codex #4 정정으로 추가

**오케스트레이션의 기본은 §4(task-dispatch)지만, "비상 원격지원"까지 비범위로 덮으면 안 된다**(Codex 지적, 재현 확인).
레포가 이미 인정하는 실수요가 있다: 보안문자/2FA 수동지원, CDP Chrome이 안 떠 있을 때 원격 기동, 멈춘 task의 화면 진단, 새 셀렉터 실측.

- **별도 면으로 분리:** 기본=Supabase pull task-dispatch / 비상=`Tailscale/VPN + macOS 화면공유/SSH` 기반 break-glass (근거: `search-ops-machine-discord-runbook-2026-06-08.md:286-289`).
- **조건 명시:** SSH/VNC/디스코드 제어 엔드포인트를 **공개 인터넷에 노출 금지**, 수동 승인 + 감사로그 필수. LinkedIn RPS는 `connect_over_cdp`로 사람이 켜둔 브라우저에 붙는 기존 방식(`browser-control-methods-comparison-2026-06-09.md:25`) 유지.
- **그래도 puppet은 primary orchestration이 아니다** — 비상·복구용으로만.

## 7. 비범위

- 남의 맥 브라우저 **원격조종을 일상 오케스트레이션의 기본 경로로** 삼기 — 안 함(§1 ②). 단 비상면은 §6.5로 인정.
- 새 메시지 브로커(Redis/Kafka 등) 도입 — 안 함. **이미 있는 Supabase** 재사용.
- 자동 발송 — 영구 비범위(SOT3).

---

## 적대 검증 로그 (2026-06-16 · strict 2패스 + 이중검증)

> 패스1=Claude 직접, 패스2=Codex 독립, 그 뒤 Claude가 Codex 증거 재현. 본문 그대로 보존.
> Codex 판정 원본 전문(111줄): `artifacts/codex-leader-control-plane-verdict.md`. 실행: codex:rescue(strict §5, 파일출력 강제).

### Codex 판정 요지 (VERDICT 줄 — 원본 본문은 위 verdict 파일)
- #1 리더 제어 평면 **부재** → **VERDICT: TRUE** (`valuehire-search-loop.sh:12-25`, `queue_runner.py:47-214` 로컬 tuple, `models.py:137-146` claimed_by/claim_token 부재, `portal_worker.py:203-214` flock 로컬, `discord_routing.py` 사람→시스템, SQL에 task_queue/account_lease/leader_lease 없음, rg 운영코드 0건).
- #2 "Supabase pull > SSH/Discord" → **VERDICT: OVERSTATED** (방향 맞으나, R4가 "자연스럽다"는 과장 — 조건부 반납·lease release·실행직전 재검증 필요. stale claim·동시 claim race·리더사망 orphan·반납/claim 토큰 경합·lease와 claim 불일치 시나리오 제시. 중앙 quota 원자성 없음: `portal_queue_executor.py:46-74`, `portal_ops.py:326-349`).
- #3 "account_lease 배정이면 원천차단" → **VERDICT: OVERSTATED** (안전은 "배정 시점" 아닌 "행동 직전 토큰 재확인"에 달림 — 형제문서 `:69-75`. 배정후 잠자기→TTL인수→깨어나 실행 시 같은 계정 충돌. L4 Hermes는 코드경로 아닌 문서약속).
- #4 "puppet 안 함, task만" → **VERDICT: OVERSTATED** (오케스트레이션 기본은 맞으나 break-glass 실수요를 "비범위"로 덮음 — `search-ops...runbook:286-289` 원격 access 가이드, `browser-control...:25` connect_over_cdp. → §6.5 추가로 정정).
- #5 "SOT 은밀히 깨지는 지점" → **VERDICT: OVERSTATED** (방향 맞으나 enforcement 위치 불명확: 링크드인 자동로그인 모순 `access.py` 주석 vs `portal_autologin.py:74-80`, R4가 중앙반납까지 안 이어짐 `queue_runner.py:65-80,201-204`, service-role 전용 모델 `portal_snapshot.py:282`이 "팔로워 scoped role"과 충돌).

### Claude의 Codex 증거 재현 (이중검증 — strict §5.2, 직접 재실행)
- **#4 재현 TRUE**: `search-ops-machine-discord-runbook-2026-06-08.md:286` "Remote access: Prefer Tailscale/ZeroTier/VPN plus macOS Screen Sharing or SSH … Do not expose … to public internet." + `browser-control-methods-comparison-2026-06-09.md:25` `connect_over_cdp` LinkedIn용. → 내 puppet 과잉배제 사실 확인 → §6.5 추가.
- **#3 재현 TRUE**: `portal_worker.py:372` `page.goto(...)` 직접. `grep hermes tools/multi_position_sourcing/*.py` → **0건**. 포털 검색은 Hermes를 안 거침 → "쓰기는 Hermes 경유"는 문서약속. 확인.
- **#5 재현 TRUE**: `access.py:54-60` "Never re-disable LinkedIn auto-login" 주석 실재(자동로그인 모순 SOT급). `selectors.py:61` `inmail_send_button_forbidden`(발송가드 실재, 좋음). `portal_snapshot.py:282` `Bearer {service_role_key}`(service-role 전용 모델 확인).

### Codex가 정정한 내 과장 (정직 공개, strict §5.3)
| # | 내 1차 주장 | Codex 판정 | 정정 |
|---|---|---|---|
| 4 | "원격조종은 비범위, 반드시 task-dispatch①" | OVERSTATED | task-dispatch가 기본은 맞으나, 비상 원격지원(2FA·화면진단·원격Chrome기동)을 비범위로 덮으면 안 됨 → **§6.5 break-glass 면 추가**. |
| 3 | "L4 쓰기/등록은 Hermes 게이트 경유" | OVERSTATED | 현 포털 worker는 Hermes를 호출하지 않음(코드 0건). 인수기준이지 기존 경로 아님 — L4를 "신규 배선 필요"로 명시해야. |
| 2/3 | "리스 보유자에게 배정 → 원천차단" | OVERSTATED | 안전은 배정시점 아닌 **행동 직전 token 재확인**에 있음. task claim과 account lease를 같은 fencing generation에 묶어야. |

### 최우선 보강 3가지 (Codex, 착수 전 반영)
1. **account_lease + task_claim을 하나의 fencing contract로** — 서버시간 RPC/CAS로만 변경, 검색/저장/발송 직전 token 재확인, R4 반납도 token 조건부 update.
2. **팔로워용 scoped auth/RLS 선설계** — service-role은 허브만, 팔로워는 task poll/claim/heartbeat/result + 자기 lease heartbeat/release만. (현 service-role 전용 확장은 SOT 위반)
3. **운영면 2분할** — 기본 pull task-dispatch + 비상 break-glass(VPN/화면공유/SSH, 권한·감사로그·수동승인 명시).
