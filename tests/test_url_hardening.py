"""조각 G — URL 검증 강화 (discord-direct-connect goal 2026-07-17 §5 G).

현 `_valid_url` 은 스킴·netloc 모양만 보고 private IP 를 통과시킨다(goal §10 정오표).
수신기가 받은 URL 이 내부망·메타데이터 서버로 향하는 SSRF 벡터를 큐 입구에서 차단한다.

인수 기준(기계 단언):
- 1단(순수, DNS 없음): IP 리터럴이 공인 대역이 아니면(loopback/private/link-local/
  reserved/multicast/unspecified) `new_job_payload` 가 None. `localhost`·`*.localhost` 도 거부.
- 2단(주입식 DNS): `url_host_resolves_public` — 해석된 주소 전부가 공인일 때만 True.
  해석 실패·빈 결과·사설 혼합(rebinding)은 False (fail-closed).
- 배선(R4): `JobQueueClient.enqueue` 가 HTTP POST 직전에 2단 검사를 강제 —
  사설로 해석되는 호스트는 ValueError, HTTP 호출 0회.
- 회귀: 기존 공개 URL(클릭업·사람인·디스코드 owner 메시지)은 계속 통과.
"""

from __future__ import annotations

import socket

import pytest

from tools.multi_position_sourcing.job_queue import (
    JobQueueClient,
    new_job_payload,
    url_host_resolves_public,
)


def _kwargs(url: str) -> dict:
    return dict(
        machine="macmini", skill="aisearch", position_url=url,
        requested_by="user:owner", role="owner", params={},
    )


# ── 1단: 순수 리터럴 판정 (DNS 없이 결정론) ──────────────────────────

@pytest.mark.parametrize("url", [
    "http://127.0.0.1/x",            # loopback
    "http://127.1.2.3:8080/x",       # loopback 대역 전체
    "http://10.0.0.1/",              # private A
    "http://172.16.0.1/",            # private B 시작
    "http://172.31.255.255/",        # private B 끝
    "http://192.168.0.10/admin",     # private C
    "http://169.254.169.254/latest/meta-data/",  # 클라우드 메타데이터(link-local)
    "http://169.254.0.1/",           # link-local 일반
    "http://0.0.0.0/",               # unspecified
    "http://224.0.0.1/",             # multicast
    "http://100.64.0.1/",            # CGNAT(공유 주소 공간)
    "http://localhost/x",            # 이름 기반 loopback
    "http://localhost:9222/json",
    "http://foo.localhost/x",        # *.localhost
])
def test_private_and_loopback_url_literals_rejected(url: str) -> None:
    assert new_job_payload(**_kwargs(url)) is None, url


@pytest.mark.parametrize("url", [
    "https://app.clickup.com/t/abc123",
    "https://www.saramin.co.kr/zf_user/search",
    "https://www.jobkorea.co.kr/Corp/Person/Find",
    "https://example.com:8443/path",
])
def test_public_urls_still_accepted(url: str) -> None:
    assert new_job_payload(**_kwargs(url)) is not None, url


def test_ipv6_literal_stays_rejected_by_netloc_shape() -> None:
    # 현 netloc 정규식이 '['를 불허해 이미 거부 — 회귀 봉인(모양 우회 금지).
    assert new_job_payload(**_kwargs("http://[::1]/x")) is None


# ── 2단: 주입식 DNS 판정 (해석 결과 전수 공인일 때만 통과) ───────────

def _resolver(*ips: str):
    def fake_getaddrinfo(host, port, *a, **k):
        if not ips:
            raise socket.gaierror("NXDOMAIN")
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0)) for ip in ips]
    return fake_getaddrinfo


def test_resolves_public_true_only_when_all_addresses_global() -> None:
    url = "https://positions.example.com/1"
    assert url_host_resolves_public(url, getaddrinfo=_resolver("93.184.216.34"))
    # 사설 단독 → 거부
    assert not url_host_resolves_public(url, getaddrinfo=_resolver("10.9.9.9"))
    # 공인+사설 혼합(DNS rebinding 류) → 거부
    assert not url_host_resolves_public(
        url, getaddrinfo=_resolver("93.184.216.34", "192.168.0.7"))
    # decimal IP 트릭(http://2130706433/)이 loopback 으로 해석되는 경우 → 거부
    assert not url_host_resolves_public(
        "http://2130706433/", getaddrinfo=_resolver("127.0.0.1"))


def test_resolves_public_fail_closed_on_failure_or_empty() -> None:
    url = "https://positions.example.com/1"
    assert not url_host_resolves_public(url, getaddrinfo=_resolver())  # 해석 실패
    def empty(host, port, *a, **k):
        return []
    assert not url_host_resolves_public(url, getaddrinfo=empty)        # 빈 결과
    def boom(host, port, *a, **k):
        raise OSError("resolver down")
    assert not url_host_resolves_public(url, getaddrinfo=boom)         # 임의 예외도 거부


def test_ipv6_scope_id_stripped_before_judgement() -> None:
    # fe80::1%en0 같은 scope 붙은 link-local 도 거부되어야 한다.
    assert not url_host_resolves_public(
        "https://positions.example.com/1", getaddrinfo=_resolver("fe80::1%en0"))


# ── Codex V1 반례 봉인 (2026-07-18) ────────────────────────────────────

def test_malformed_ipv6_url_is_fail_closed_not_exception() -> None:
    # V1-F1: 잘못 닫힌 IPv6 URL 이 안전한 False 대신 ValueError 를 던지면 fail-closed 위반.
    for bad in ("https://[::1/x", "https://[gggg::]/x", "http://[/"):
        assert url_host_resolves_public(bad, getaddrinfo=_resolver("93.184.216.34")) is False, bad


def test_site_local_ipv6_fec0_is_not_public() -> None:
    # V1-F2: fec0::/10 site-local 은 (deprecated 라도) 내부망 — ipaddress.is_global 이
    # True 로 오판하므로 명시 차단해야 한다. ULA(fc00::/7)·link-local 도 함께 봉인.
    for internal in ("fec0::1", "fec0:0:0:1::5", "fc00::1", "fd12:3456::1", "fe80::1"):
        assert not url_host_resolves_public(
            "https://positions.example.com/1", getaddrinfo=_resolver(internal)), internal


def test_public_ipv6_still_accepted_via_real_sockaddr_shape() -> None:
    # 공인 IPv6 는 4-튜플 sockaddr(AF_INET6) 형상으로 와도 통과해야 한다.
    def v6_resolver(host, port, *a, **k):
        return [(socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2606:4700:4700::1111", 0, 0, 0))]
    assert url_host_resolves_public("https://positions.example.com/1", getaddrinfo=v6_resolver)


@pytest.mark.parametrize("url", [
    "http://2130706433/x",       # decimal 정수형 = 127.0.0.1
    "http://0177.0.0.1/x",       # 8진 선행 0 = 127.0.0.1
    "http://0x7f.0.0.1/x",       # 16진 옥텟
    "http://127.1/x",            # 축약형 = 127.0.0.1
    "http://010.0.0.1/x",        # 8진 = 8.0.0.1(공인이지만 표기 자체가 기만적)
])
def test_numeric_ip_lookalike_hosts_rejected_at_stage1(url: str) -> None:
    # V1-F5: 십진/8진/16진 IP 기만 표기는 DNS 없이도 1단에서 거부(방어심층).
    assert new_job_payload(**_kwargs(url)) is None, url


# ── V2 리셋 재검증 반례 봉인: NAT64/6to4 임베드 사설IP (2026-07-18) ──────

def test_nat64_wellknown_prefix_embedding_private_ipv4_rejected() -> None:
    # V2-F6: 64:ff9b::/96(NAT64 well-known, RFC6052)에 사설/loopback/메타데이터 IPv4 를
    # 임베드하면 ipaddress.is_global 이 True 로 오판 → NAT64 게이트웨이가 있는 호스트에서
    # 실제 사설 IPv4 로 라우팅될 수 있다. 임베드된 IPv4 를 추출해 재판정해야 한다.
    cases = {
        "64:ff9b::127.0.0.1": "loopback 임베드",
        "64:ff9b::a00:1": "10.0.0.1 사설 임베드",
        "64:ff9b::a9fe:a9fe": "169.254.169.254 메타데이터 임베드",
        "64:ff9b::c0a8:1": "192.168.0.1 사설 임베드",
    }
    for addr, why in cases.items():
        assert not url_host_resolves_public(
            "https://positions.example.com/1", getaddrinfo=_resolver(addr)), why


def test_nat64_embedding_public_ipv4_still_allowed() -> None:
    # NAT64 에 공인 IPv4(93.184.216.34)를 임베드한 것은 실제로 공인으로 라우팅되므로 통과.
    assert url_host_resolves_public(
        "https://positions.example.com/1", getaddrinfo=_resolver("64:ff9b::5db8:d822"))


# ── 배선(R4): enqueue 가 POST 직전 DNS 검사를 강제 ────────────────────

def _client(resolver) -> JobQueueClient:
    return JobQueueClient(url="https://example.supabase.co", key="k",
                          getaddrinfo=resolver)


def test_enqueue_blocks_privately_resolving_host_before_http(monkeypatch) -> None:
    c = _client(_resolver("192.168.77.1"))
    calls: list = []
    monkeypatch.setattr(c, "_call", lambda *a, **k: calls.append(a) or [{"id": 1}])
    payload = new_job_payload(**_kwargs("https://internal.example.com/pos/1"))
    assert payload is not None  # 모양은 유효 — 리터럴 판정으로는 못 잡는 케이스
    with pytest.raises(ValueError):
        c.enqueue(payload)
    assert calls == [], "사설 해석 호스트는 HTTP 호출 자체가 없어야 한다"


def test_enqueue_allows_publicly_resolving_host(monkeypatch) -> None:
    c = _client(_resolver("93.184.216.34"))
    calls: list = []
    monkeypatch.setattr(c, "_call", lambda *a, **k: calls.append(a) or [{"id": 7}])
    payload = new_job_payload(**_kwargs("https://positions.example.com/1"))
    assert c.enqueue(payload) == {"id": 7}
    assert len(calls) == 1
