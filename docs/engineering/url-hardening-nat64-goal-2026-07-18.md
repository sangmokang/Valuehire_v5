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

## 범위 확대 (V1 반례 반영 — 2000::/3 화이트리스트로 일반화)
- 최초 수정은 NAT64 well-known(64:ff9b::/96)만 다뤘으나, V1(Codex read-only)이 같은 부류의 추가 우회를 지적: `::169.254.169.254`(IPv4-compatible ::/96, 메타데이터)·`::ffff:0:127.0.0.1`(IPv4-translated ::ffff:0:0/96) 등이 여전히 is_global True.
- 근본 수정: **공인 IPv6 는 IANA 상 오직 global unicast(2000::/3) 안에만 배정**되므로, IPv6 판정을 "그 밖의 특수목적 대역은 fail-closed 거부 + IPv4-mapped·NAT64 임베드만 임베드 IPv4 로 재판정"으로 바꿔 whack-a-mole 없이 일괄 차단. IPv4 는 기존 is_global 경로 유지.

## 비범위
- params.search_urls(워커가 페치하는 실경로)의 동일 하드닝 — 여전히 조각 B 후속(V2도 실위험 후보로 지목).
- 워커 실행 시점 재해석(TOCTOU) — 큐 입구 차단이 이번 범위.
- IPv4-compatible/translated 형식에 **공인** IPv4 를 임베드한 것도 2000::/3 밖이라 거부됨(fail-closed) — 이 구식 형식은 실 getaddrinfo 반환에 나타나지 않아 가용성 손실 없음(막는 방향이라 안전).
- V1 정확성 지적 수용: "표준 64:ff9b::/96 에 비공인 IPv4 패킷은 규격상 번역기가 폐기" — 실 라우팅은 번역기 비준수/오설정 조건이 필요. 방어는 심층방어(defense-in-depth)이며 goal 위험 서술을 이 조건으로 정직화함.

## 적대 검증 로그
- 발견: V2 리셋 재검증(NAT64) + V1 read-only(추가 IPv6 임베드 형식). G 직접 재현으로 두 부류 실결함 확정.
- 3자 대조·재확인: verdict.json 참조.
