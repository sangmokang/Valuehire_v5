# goal — 디스코드 결정적 4W 라우팅 + 로그인 우선 + Hook 강제 (Hermes 컷오버 완주)

> 작성 2026-07-24 (사장님 /st + /goal 지시). 등급 **L3**(SOT 수정·인증/로그인·게이트웨이 컷오버·Hook 강제).
> 상위 계약: SOT-33(Hermes 폐기) · SOT-32(자연어 셸 라우팅) · SOT-29(함대·큐) · SOT-26(포털 로그인) · SOT-31(신뢰성).
> 이 goal은 새 시스템을 만들지 않는다 — **이미 착수된 SOT-33 컷오버를 사장님 오늘 Needs(4W+로그인+Hook)에 맞춰 완주**하는 문서다.

## 0. 사장님 Needs (원문 정규화 — 이것이 Spec의 뿌리)

> "내 명령들은 명료하다. **어떤 포지션을, 어떤 사이트에서(링크드인·사람인·잡코리아), 어느 PC에서, 어디에서 찾을 것인가.** 현재는 이 Needs에만 집중한다. **로그인이 최우선 과제.** Spec화 처리하고 **Hook으로 예외 없이** 돌아가도록 해. Shell 창처럼 처리한다는 요구는 변함없지만 지금 프롬프팅은 이 4W에 집중."

4W 정의:
- **W1 포지션(무엇)**: ClickUp task URL 또는 포지션 식별자.
- **W2 사이트(어디서 찾나)**: `linkedin` | `saramin` | `jobkorea` (channels).
- **W3 PC(어느 기계)**: `macmini` | `winpc` | `macbook` (machine).
- **W4 방식(어떻게 찾나)**: skill = `humansearch` | `aisearch` | `url`.

## 1. 현재 상태 (라이브 확정 — 추측 아님, file:line/증거)

1. **게이트웨이 2개 동시 가동, 같은 봇 토큰**(지문 `579cadd7e610`):
   - Hermes: PID 79255, 두뇌 `openai-codex/gpt-5.5` (`~/.hermes/config.yaml:3`), `DISCORD_BOT_TOKEN` 사용.
   - 직결 게이트웨이: PID 33128, `scripts/discord_direct_gateway.py`(`DISCORD_BOT_TOKEN` line 703/959).
   - → **SOT-33 절대규칙 2·3 위반**. 디스코드는 봇 토큰당 안정 연결 1개 → 이벤트 비결정 분배.
2. **Hermes가 코덱스 LLM 판단으로 job.machine 임의 결정**:
   - job #76 (Supabase 라이브): `machine=winpc, skill=aisearch, channels=[saramin], status=paused_for_human, error="로그인 선행 게이트: 로그인 영수증 없음"`. 사장님은 머신 미지정("saramin 에서 실시")인데 winpc로 배정됨.
3. **결정적 파서는 이미 4W를 전부 파싱**: `hermes_fleet_bridge.natural_fleet_command_text` (tools/multi_position_sourcing/hermes_fleet_bridge.py:105-197) — machine(124-130), channels(166-177), skill(179-180), url. **머신 미지정 시** `fleet_dispatch.py:62` → 기본 `macmini`. **그러나 Hermes 코덱스 경로가 이 파서를 우회**한다.
4. **직결 게이트웨이는 결정적·enqueue-only**: `discord_direct_gateway.py` INV-D1(스스로 실행 안 함), INV-D5(최소권한). HR-1 로컬 게이트 초록(#184 커밋들). 하지만 Hermes와 동시 가동이라 이벤트를 확실히 못 받음.
5. **로그인 SOT-26**(`docs/sot/26-portal-login-spec.json`, raw CDP 자동로그인) 존재, `login-first-fast-ack` 워크트리 진행 중(`8c8c7ae fix: acknowledge search commands and preflight login`).
6. **진행 중 워크트리 다수**: `hr1-live-acceptance`, `discord-login-first-fast-ack`, `discord-search-inputs`, `discord-owner-agent-queue/runtime`. → **병렬 세션 충돌 주의**(남의 워크트리 불가침).

## 2. 근본 원인 (3층)

Hermes(코덱스 LLM 판단 계층)가 ① 아직 디스코드를 받고 ② 결정적 파서를 우회해 ③ 직결 게이트웨이와 같은 봇 토큰으로 동시 가동 → 4W 중 W3(PC)가 코덱스 임의 선택으로 오염. **컷오버(Hermes 중단 → 직결 단독)가 미완**이라 발생.

## 3. Spec (결정적 계약)

- **S1 단일 수신기**: 봇 토큰당 활성 게이트웨이 정확히 1개. 디스코드 명령은 **코덱스 판단 없이** 직결 게이트웨이 → 결정적 파서만 거친다.
- **S2 W3 기본값 결정성**: 머신 미지정 → `macmini`. 코덱스/휴리스틱의 임의 머신 선택 금지. 이전 대화 맥락으로 머신 상속 금지.
- **S3 로그인 최우선**: 검색 job 실행 전, 대상 (machine×channel) 로그인 영수증(`artifacts/portal_session_status_latest.json`, ready=True) 선행. 없으면 로그인 job을 먼저 세운다(SOT-26). — 이것이 사장님 "로그인 최우선".
- **S4 Hook 예외 없이**: Hermes 재기동을 production 기동 게이트 + PreToolUse Hook **이중**으로 차단(SOT-33 규칙 6). 직결 게이트웨이 lease 없이는 어느 수신기도 기동 불가.

## 4. 인수 기준 (EARS + 검증 명령, AC 1개=단위 1개)

- **AC1 (W3 결정성)**: WHEN 디스코드에 머신 미지정 검색 명령 유입 THEN 생성 job.machine == `macmini`. 
  - 검증: 직결 경로 단위테스트(`tests/test_discord_direct_gateway.py` 확장) — "머신 토큰 없는 자연어 → envelope.machine 공란 → enqueue시 macmini".
  - counter-AC: "winpc"/"윈도우" 명시 → machine==winpc (결정적, 임의 아님).
- **AC2 (단일 수신기 Hook)**: WHEN Hermes 게이트웨이 기동 시도 AND 직결 게이트웨이 lease 활성 THEN 기동 거부(exit≠0, fail-closed). 검증: 기동 게이트 테스트 + Hook 테스트.
- **AC3 (로그인 우선)**: WHEN 검색 job claim 시 대상 (machine×channel) 영수증 부재 THEN 검색 전에 로그인 선행(job 또는 preflight), 임의 진행 금지. 검증: `fleet_worker` 로그인 게이트 테스트(기존 `login_gate_block_reason`) + 로그인 job 자동 선행.
- **컷오버 전제(SOT-33 규칙4·5)**: queued/running/paused_for_human == 0 확인 + engine=claude·codex 라이브 인수 각 1건 done → 그 후에만 Hermes 중단.

## 5. Hook 강제 계획 (SOT-33 §2 규칙6 이중)

- **H1 게이트웨이 lease**: 봇 토큰당 1개 lease(Supabase/파일). 직결 게이트웨이가 보유. Hermes는 lease 없어 기동 거부.
- **H2 Hermes 기동 차단**: production fail-closed 기동 게이트 + PreToolUse Hook(`guards/`)로 Hermes gateway 기동/plist 로드 물리 차단.
- **H3 W3 결정성 가드**: enqueue시 machine 값이 {macmini,winpc,macbook} 또는 공란(→macmini)만 허용, 그 외 거부.

## 6. 기존 정의 연결 (회수 완료)

SOT-33(§1 목표경로·§2 규칙·§3 HR단계) · SOT-32(자연어 4W 어휘 — **단 머신 어휘는 JSON에 없음, 추가 검토**) · SOT-29(account_key=portal:<machine>·워커 자기머신 claim) · SOT-26(로그인) · `hermes_fleet_bridge.py`(결정적 파서) · `discord_direct_gateway.py`(직결) · #184 HR-1 · 진행 워크트리들.

## 7. 비범위

- "Shell 창처럼 처리(자연어 전반 확장)" — 요구는 유지되나 사장님이 이번엔 4W에 집중 명시. 별도.
- 실제 Hermes 파일 삭제(HR-6~7) — 이번은 **중단(컷오버)**까지. 삭제는 SOT-33 후속 단계.
- 다른 세션이 점유한 워크트리 코드 수정.

## 8. 적대 검증 정조준 (V1/V2가 공격할 지점)

- 봇 토큰 1개 = 디스코드 게이트웨이 연결 1개 강제인가? 두 프로세스가 실제로 어떻게 이벤트를 나눠 받나(중복/누락)?
- 직결 단독 전환 시 4W가 전부 결정적으로 job에 반영되는가(W2 channels·W4 skill 포함)?
- S2 "이전 맥락 머신 상속 금지"가 코덱스 제거만으로 충족되나, 별도 상태가 남아있나?
- 로그인 선행(S3)이 무한 루프/영구 pause를 만들지 않는가(SOT-31 60초 자동재개와 상호작용).

## 9. 롤백 절차 (L3)

- 컷오버 실패 시: Hermes 재기동(lease 반환) → 직결 게이트웨이 중단. 봇 토큰 1개 원칙 유지(동시 가동 금지).
- 백업: `~/.hermes/.env` 이미 다중 백업 보유. job 상태는 Supabase(cancel/resume RPC).

## 적대 검증 로그
(후기록 — V1/V2 판정 append)
