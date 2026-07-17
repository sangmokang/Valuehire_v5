# Goal — NAT64 임베드 사설IP 우회 차단 (escaped-defect F6)

- 근거: PR#145(discord-url-hardening) 병합 후 /strict 재검증에서 V2(리셋 Claude)가 찾은 신규 구멍. G·V1(Codex) 공유 사각지대.
- 모드: code-change / 위험등급: L3 (SSRF 보안 강화 — strict "보안 걸리면 무조건 L3")
- 게이트 6 진화(escaped-defect): 병합된 코드에서 새어나온 결함 → 잡는 검사(RED) 먼저 → 고침.

## 현재 상태 (수정 전, main c307785)
- `_ip_is_global`(job_queue.py:108)이 NAT64 well-known prefix `64:ff9b::/96`(RFC6052)를 특별취급하지 않음.
- 재현: `_ip_is_global("64:ff9b::127.0.0.1")=True`, `64:ff9b::a9fe:a9fe`(=169.254.169.254 메타데이터)=True → `url_host_resolves_public` 가 True 반환 → NAT64/DNS64 게이트웨이가 있는 함대 머신에서 실제 사설 IPv4 로 라우팅 가능.
- 대조군은 정상 차단: `::ffff:127.0.0.1`(IPv4-mapped), `2002:7f00:1::`(6to4) 는 이미 is_global=False.

## 계약
- `_nat64_embedded_ipv4(addr)`: 주소가 `64:ff9b::/96` 안이면 하위 32비트를 IPv4 문자열로 반환, 아니면 None(순수함수).
- `_ip_is_global`: NAT64 주소면 임베드 IPv4 를 추출해 그 IPv4 의 공인 여부로 재판정. 공인 IPv4 임베드(예: `64:ff9b::5db8:d822`=93.184.216.34)는 계속 통과, 사설/loopback/메타데이터 임베드는 거부.

## 인수 기준
- [x] 기계: NAT64 사설/메타데이터 임베드 4종 거부 + 공인 임베드 1종 통과 테스트 GREEN. 기존 32개 무손상. ./verify.sh exit 0(실측 verdict 기록).
- [x] 뮤턴트: 추출 무력화(항상 None) → nat64 테스트 1 failed 감지 후 원복.
- [ ] 4b: V1(Codex)·V2(리셋) 재확인.

## 비범위
- RFC8215 로컬 NAT64 프리픽스(64:ff9b:1::/48)는 ipaddress 가 이미 is_global=False → 별도 차단 불필요(회귀 테스트 후보).
- params.search_urls(워커가 페치하는 실경로)의 동일 하드닝 — 여전히 조각 B 후속(V2도 실위험 후보로 지목).
- 워커 실행 시점 재해석(TOCTOU) — 큐 입구 차단이 이번 범위.

## 적대 검증 로그
- 발견: V2 리셋 재검증(agent transcript tasks/a829054a4e6717723.output). G 직접 재현으로 실결함 확정.
- V1/V2 재확인: verdict.json 참조.
