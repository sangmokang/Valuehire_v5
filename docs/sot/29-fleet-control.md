# SOT29 — 함대 통제 (3대 머신 · Discord 명령 · 계정↔머신 바인딩)

> 2026-07-11 확정. 맥미니 1 + 맥북프로 1 + 사무실 윈도우PC 1 로 서치 체계를 확장하며,
> Discord 명령으로 컨설턴트가 서치를 시키고 사장님이 원격에서 통제하는 구조의 정본.
> 기계 명세(불변식)는 `29-fleet-control.json`. 절대 규칙 5개(로그인 유지·크롬 양보·발송 게이트·
> 브라우저 보존·한국어 보고)의 상위 제약은 그대로다 — 본 문서는 그 위에서 함대를 배선한다.

## 1. 구성 요소 (전부 병합 완료)
- **작업 큐**(PR #83): Supabase `jobs`+`account_locks` + claim/release/resume/cancel RPC.
- **워커**(PR #84): `tools/multi_position_sourcing/fleet_worker.py` — 자기 머신 큐를 폴링해
  `claude -p` 로 스킬 잡 실행, 캡차 시 `PAUSED_FOR_HUMAN`, 결과 한국어 Discord 보고.
- **Discord 명령**(PR #85): `fleet-run`(멤버·owner) / `fleet-status` / `fleet-resume`·`fleet-cancel`(owner 전용).
- **owner 일반 스킬 작업**(#138): 현재 Discord 메시지 원문을 `skill=agent` 잡 1건으로 보존한다.
  실행기는 `codex`가 기본이고 `claude`를 명시할 수 있다. 멤버용 검색 작업과 별도 lane이다.
- **heartbeat/watchdog**(단계 G): 1분 심장박동 + 5분 stale 경보(30분 억제).

## 2. 계정 ↔ 머신 1:1 바인딩 (가장 큰 안전장치)
- **같은 포털 계정을 3대에서 동시에 돌리지 않는다.** 다중 세션은 서로를 밀어내 자동 로그인(절대규칙 1)을
  스스로 깨고, LinkedIn 은 시트 라이선스라 약관 위반이다.
- 각 머신의 크롬 디버그 프로필에는 **그 머신 전용 계정만** 로그인한다.
- 잡의 `account_key`(기본 `portal:<machine>`)로 **계정 글로벌 락**을 건다 — 같은 계정은 한 시점에 한 머신만.
- **계정 단위 pause 장벽**: 같은 공백문자 없는 `account_key`에 `paused_for_human` 잡이 하나라도 있으면
  새 잡 등록은 보존하되 서버가 그 계정의 claim/execute를 막는다. 다른 계정은 계속 실행한다.
  시간 만료는 없으며, 같은 키의 모든 일시정지 잡을 `resume_job` 또는 `cancel_job`으로 해소해야 풀린다.
- LinkedIn 공용 키 `portal:linkedin_rps`에도 머신과 무관하게 같은 장벽을 적용한다. 신규·변경되는
  실행 대상 잡의 공백 `account_key`는 거부한다. 과거 대기·일시정지 공백 키는 기본 정책으로
  보정하고, 실행 중 공백 키가 있으면 배포를 멈춰 수동 확인한다.
- **LinkedIn 잡(skill=url)은 heartbeat 의 `linkedin_rps_logged_in` 상태를 보고 로그인된 머신으로
  라우팅한다**(2026-07-15 사장님 승인 개정 — 이전 "macmini 전용" 조항 대체). 로그인 머신이 여럿이면
  INV8 신뢰도 순(macmini > winpc > macbook), **아무도 로그인 안 돼 있거나 조회 실패면 macmini 폴백**.
  계정 글로벌 락(account_key)은 그대로라 같은 계정 동시 2머신 실행은 여전히 불가능하다.
- IP 일관성: 3대가 같은 사무실 공유기 뒤면 충족. 흩어지면 맥미니를 Tailscale exit node 로 출구 통일.

## 3. 크롬 로그인 프로필 보존 (삭제·초기화 금지)
- 각 머신의 `--user-data-dir` 디버그 프로필 디렉터리는 **삭제·초기화 금지 대상**이다(절대규칙 4).
- 잡 일시정지(`paused_for_human`) 중에도 크롬 탭·프로필을 닫지 않는다.
- 로그인된 포털 크롬은 kill/stop 금지(메모리 keep-logged-in-browser-alive 와 동일).

## 4. 사람 개입 흐름 (캡차/2FA)
1. 워커가 캡차/2FA 감지 → 잡을 `paused_for_human` 전환 + 크롬 조작 중단(양보).
2. Discord 로 머신명·잡ID·상황 알림.
3. 사장님이 VNC(맥) 로 접속해 수동 처리(브라우저 앞으로).
4. Discord `fleet-resume job:<id>` → 워커 재개.
- 워커는 일시정지 중 절대 크롬을 닫지 않는다.
- **INV9 · 사장님 양보 60초(1분) 자동 재개 + 3사 포털 한정 (2026-07-20 사장님 지시로 개정, 원본 2026-07-15 #107)**: 사장님 개입으로 보는 것은 **크롬 활성 탭이 3사 포털(사람인·잡코리아·링크드인)일 때뿐**이다 — 유튜브 등 다른 화면 사용은 개입이 아니며 자동작업을 멈추지 않는다. 3사 개입 또는 사람 개입 신호(캡차·2FA·paused) 후에는 자동작업(다음 잡 claim·변형 enqueue)을 멈추되, 마지막 신호로부터 **60초(1분)** 동안 이상이 없으면 **자동 재개**한다(로그인 포함 — 로그인 우선순위 최상). 자동 재개를 영구 차단하는 코드(backlog 폐기·무기한 중단·10분 고정 쿨다운)는 SOT 위반이며 삭제 대상.
  단일 출처: `fleet_worker.OWNER_YIELD_RESUME_SECONDS = 60`, `owner_activity.DEFAULT_OWNER_IDLE_THRESHOLD_SECONDS = 60`, `owner_activity.PORTAL_HOSTS`.
- 같은 계정에 일시정지 잡이 여러 건이면 일부만 재개·취소해도 장벽은 풀리지 않는다.

## 5. 권한
- `fleet-run` / `fleet-status`: 인가된 멤버·owner.
- `fleet-resume` / `fleet-cancel`: **owner 전용**(사장님). owner 는 명시적 Discord ID(`OWNER_USER_IDS`,
  기본 814353841088757800)로 판정하며 멤버 연락처 목록과 분리한다.
- 멤버·자동 실행 lane은 `humansearch`·`aisearch`·`url`만 허용하며 아웃리치 발송을 트리거하지
  못한다(SOT28 발송 게이트 유지).
- owner 일반 스킬 lane은 **사장님의 현재 메시지 한 건**만 승인 범위로 삼는다. `role=owner`,
  `skill=agent`, `agent=codex|claude`, `approval_id=discord:<message_id>`, 원문 `prompt_sha256`,
  원문·실행기·실행모드·승인번호를 묶은 `approval_sha256`, `idempotency_key=approval_id`를 함께
  검증한다. 같은 메시지는 한 번만 등록하며, 멤버 요청·후속 자동
  작업·원문 해시 불일치는 거부한다. 외부 발송이 적힌 경우에도 그 메시지에 명시된 대상·채널·횟수를
  넓혀 해석할 수 없다.

## 6. 무중단 목표의 정직한 평가
- 100% 무중단은 불가능(OS/Chrome 업데이트·재부팅·정전·맥북 발열/배터리·FileVault). 목표는
  **무인 가동 + 자기복구 + 빠른 경보**다.
- **주 1회 유지보수 창**(일요일 새벽)에 OS/Chrome 업데이트를 몰아서 적용.
- 자기복구 체인: 재부팅 → 자동 로그온 → 워커 자동 기동(launchd/작업스케줄러) → 크롬 디버그 프로필 → 큐 재개.
- watchdog: 5분 무응답 → OPS_HEALTH 경보(PR#66 이 못 잡는 "죽었는데 아무도 모름" 보완).
- **머신 신뢰도 서열: macmini(최상) > winpc(Update 관리 전제 시 상) > macbook(보조 캐파 — 발열·배터리·FileVault).**
  맥북은 기본 캐파가 아니라 오버플로/특정 계정 전용 보조로 배치한다.

## 7. 하드웨어 셋업 체크리스트 (사장님 수동 — 코드 아님)
- **Tailscale**: 3대 + 사장님 폰 설치, ACL 로 "SSH/VNC 는 사장님만". 공인망 노출 포트 0개(CDP·VNC·SSH 전부 Tailscale).
- **맥북**: 전원 상시 + HDMI 더미 플러그 + 클램셸, 배터리 80% 제한, FileVault 결정(사무실 상주면 해제),
  launchd 워커 세트 복제(`VALUEHIRE_MACHINE=macbook`).
- **윈도우**: Claude Code 네이티브 설치 + Sysinternals Autologon + 작업 스케줄러(**interactive, 서비스 금지** —
  Session 0 함정), 전용 크롬 디버그 프로필(`--user-data-dir`, Chrome 136+ 필수), VNC/RustDesk(**RDP 금지**).
- 각 머신에서 `claude -p "hi"` 1회 성공(로그인 확인) 후 워커 plist/스케줄러 설치.

## 8. 워커/워치독 설치 (plist 초안 제공, 설치는 수동)
- `ops/launchd/com.valuehire.fleet-worker.plist` — 머신마다 `VALUEHIRE_MACHINE` 반드시 수정.
- `ops/launchd/com.valuehire.fleet-watchdog.plist` — **맥미니 1곳에서만** 상주.
