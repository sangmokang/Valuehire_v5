# Goal — URL 검증 강화 (discord-direct-connect 조각 G)

- 근거: docs/prompts/discord-direct-connect-goal-2026-07-17.md §5 G, §6-5, §10 정오표("_valid_url 은 private IP 통과").
- 모드: code-change / 위험등급: L2 (검증 강화 — 발송·로그인·파괴 동작 없음, 큐 입구 1파일)

## 현재 상태 (수정 전)
- `job_queue._valid_url`(job_queue.py:74)은 스킴·netloc 모양·포트만 검사 — `http://127.0.0.1/`, `http://10.0.0.1/`, `http://169.254.169.254/`(클라우드 메타데이터), `http://localhost/` 가 전부 통과해 큐에 들어갈 수 있었다(SSRF 벡터).
- 이름 기반 호스트(내부망으로 해석되는 도메인)는 어떤 계층에서도 차단 안 됨.

## 계약 (스펙 먼저)
- 1단(순수): `_host_forbidden_literal(host) -> bool` — localhost/*.localhost + 비공인 IP 리터럴(loopback·private·link-local·reserved·CGNAT·multicast·unspecified). `_valid_url` 에 통합, DNS 없음(결정론).
- 2단(주입식): `url_host_resolves_public(url, *, getaddrinfo) -> bool` — 해석 주소 **전수** 공인일 때만 True. 혼합(rebinding)·실패·빈 결과 = False(fail-closed).
- 배선: `JobQueueClient.enqueue` 가 POST 직전 2단 강제(생성자 `getaddrinfo=` 주입, 기본 실 DNS). 모든 enqueue 경로(hermes bridge·fleet_dispatch·직결 수신기 예정)가 이 관문을 지난다.

## 인수 기준
- [x] 기계: tests/test_url_hardening.py 24개 GREEN(RED 커밋 50bd1e3 → GREEN 62c187c), 기존 test_job_queue 82개 무손상, ./verify.sh exit 0(실측치는 verdict 기록).
- [x] 뮤턴트: DNS검사 상수화→4 failed / localhost 제거→3 failed / is_global 상수화→14 failed. 전부 감지 후 원복.
- [ ] 4b: Codex Rescue 독립 반증 통과.

## 비범위 / 정직한 한계
- params.search_urls(검색결과 URL 목록)의 동일 검사 — 조각 B(enqueue-or-get)와 함께 다룰 후보.
- 워커 실행 시점 재검증(TOCTOU: enqueue 후 DNS 가 바뀌는 경우) — 큐 입구 차단이 이번 범위.
- IPv6 리터럴은 기존 netloc 정규식이 이미 모양으로 거부(회귀 테스트로 봉인만).
- **DNS 장애 시 fail-closed(Codex V1-F3, 수용된 한계)**: enqueue 가 실 DNS 해석에 의존하므로,
  네트워크·DNS 장애 중에는 정상 공개 URL(클릭업·디스코드) 잡도 거부된다. 이는 goal §5 G가
  명시한 "해석 실패·빈 결과 fail-closed" 계약 그대로다(가용성보다 SSRF 안전 우선). Discord
  경로는 오류를 사용자에게 명시 회신(무음 유실 아님), 워커 자동변형은 다음 idle 사이클에 재시도.
  **후속 후보**: 해석 실패(일시)와 사설 해석(차단)을 구분해 일시 실패엔 재시도 큐로 보내는
  개선(별도 조각) — 이번 범위에서는 계약 준수를 우선.

## 적대 검증 로그
- G 자기반증: decimal IP(2130706433)·hex·선행 0 리터럴은 1단을 지나가지만 2단 DNS 판정에서 잡힘(테스트 포함). 기존 `_fake_client` 실 DNS 오염 발견 → 공인 fake resolver 주입으로 봉인.
- V1(Codex): verdict.json 참조.
