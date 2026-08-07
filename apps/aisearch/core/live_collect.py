"""라이브 포털 채널 수집 — 이미 검증된 CdpDriver 메서드만 조합하는 얇은 배선.

배경: raw CDP 즉흥 타이핑(문자별 dispatchKeyEvent, clipboard API)이 사람인/
잡코리아 라이브 계정에서 실패했다(입력 미반영, clipboard 권한 프롬프트로
Runtime.evaluate 행). apps/aisearch/core/cdp_driver.CdpDriver 는 이미 신뢰
입력(Input.insertText)+로드 대기+캡차/2FA 감지까지 검증된 드라이버이므로,
이 모듈은 그 검증된 포트(fetch_list_page/fetch_detail_page)만 순서대로
호출한다 — 셀렉터·입력 로직은 새로 만들지 않는다(재사용, 복제 금지).
"""
from __future__ import annotations

from typing import Any, Mapping, Protocol


class ChannelDriverPort(Protocol):
    def fetch_list_page(self, channel: str, page: int, payload: Mapping[str, Any]) -> dict: ...
    def fetch_detail_page(self, channel: str, ref: str) -> dict: ...


def collect_channel_pages(
    driver: ChannelDriverPort,
    channel: str,
    descriptor: Mapping[str, Any],
    *,
    max_pages: int,
) -> list[dict]:
    """채널 하나를 최대 ``max_pages`` 까지 순회하고 상세까지 전부 연다.

    페이지 1..max_pages 순서로 ``driver.fetch_list_page`` 를 호출하고, 각
    결과의 ``detail_refs`` 를 ``driver.fetch_detail_page`` 로 전부 열어
    ``pages[i]['details']`` 에 담는다. ``has_next=False`` 를 만나거나
    ``max_pages`` 에 도달하면 더 이상 요청하지 않는다.
    """
    if max_pages < 1:
        raise ValueError(f"max_pages 는 1 이상이어야 한다: {max_pages!r}")

    pages: list[dict] = []
    for page in range(1, max_pages + 1):
        result = dict(driver.fetch_list_page(channel, page, descriptor))
        result["details"] = [
            driver.fetch_detail_page(channel, ref) for ref in result["detail_refs"]
        ]
        pages.append(result)
        if not result["has_next"]:
            break
    return pages
