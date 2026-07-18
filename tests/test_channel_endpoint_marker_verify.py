"""마커 검증 endpoint 발견 (TODO-2b 조각 B 핵심, 라이브 없이 모킹).

라이브 실측(2026-07-18): 실제 포트가 스크립트 기본과 뒤섞임(9222=사람인, 9223=잡코리아).
채널→기본포트만 믿고 attach 하면 사람인 작업이 잡코리아 크롬에 붙는 오접속 사고.
⇒ 후보 endpoint 를 얻되, 그 endpoint 탭에 대상 사이트 로그인 마커가 실제 있는지
검증한 뒤에만 채택. 없으면 다른 살아있는 포트를 마커로 재탐색(SOT-26 §2 발견 알고리즘,
v4 cdp-endpoints.mjs 계층 match 동형). raw 단일탭 방식(SOT-26 INV5) 준수 — 전체
connectOverCDP 아님.
"""

from __future__ import annotations

import unittest

from tools.multi_position_sourcing.portal_worker import find_verified_channel_endpoint


def _tabs(*urls):
    return [{"type": "page", "url": u} for u in urls]


class FindVerifiedChannelEndpointTests(unittest.TestCase):
    def test_primary_port_with_marker_is_chosen(self) -> None:
        # 정상: 채널 1차 후보(saramin=9223)에 사람인 탭이 있으면 그대로.
        def list_tabs(ep):
            return _tabs("https://www.saramin.co.kr/zf_user/x") if ":9223" in ep else []
        self.assertEqual(
            find_verified_channel_endpoint("saramin", list_tabs=list_tabs, env={}),
            "http://127.0.0.1:9223",
        )

    def test_misplaced_ports_are_corrected_by_marker(self) -> None:
        # 라이브 실측 재현: 9223 엔 잡코리아, 9222 에 사람인 → 사람인은 9222 로 교정.
        def list_tabs(ep):
            if ":9223" in ep:
                return _tabs("https://www.jobkorea.co.kr/Corp/Person/Find")
            if ":9222" in ep:
                return _tabs("https://www.saramin.co.kr/zf_user/memcom")
            return []
        self.assertEqual(
            find_verified_channel_endpoint("saramin", list_tabs=list_tabs, env={}),
            "http://127.0.0.1:9222",
            "1차 후보에 마커 없으면 마커 있는 포트로 재탐색해야(오접속 방지)",
        )

    def test_jobkorea_not_confused_with_saramin(self) -> None:
        def list_tabs(ep):
            if ":9222" in ep:
                return _tabs("https://www.saramin.co.kr/x")
            if ":9223" in ep:
                return _tabs("https://www.jobkorea.co.kr/Corp/Person/Find")
            return []
        # 잡코리아는 9223(잡코리아 탭 있는 곳)을 골라야 — 9222(사람인)에 붙으면 안 됨.
        self.assertEqual(
            find_verified_channel_endpoint("jobkorea", list_tabs=list_tabs, env={}),
            "http://127.0.0.1:9223",
        )

    def test_dead_port_is_skipped(self) -> None:
        def list_tabs(ep):
            if ":9223" in ep:
                raise ConnectionError("dead")
            if ":9224" in ep:
                return _tabs("https://www.saramin.co.kr/x")
            return []
        self.assertEqual(
            find_verified_channel_endpoint(
                "saramin", list_tabs=list_tabs, env={}, candidate_ports=[9223, 9224]),
            "http://127.0.0.1:9224",
        )

    def test_no_marker_anywhere_raises(self) -> None:
        def list_tabs(ep):
            return _tabs("https://www.google.com")
        with self.assertRaises(LookupError):
            find_verified_channel_endpoint("saramin", list_tabs=list_tabs, env={})

    def test_explicit_endpoint_value_still_marker_checked(self) -> None:
        # 명시 endpoint 라도 그 곳에 마커 없으면 오접속 — raise (맹목 신뢰 금지).
        def list_tabs(ep):
            return []  # 어디에도 마커 없음
        with self.assertRaises(LookupError):
            find_verified_channel_endpoint(
                "linkedin_rps", list_tabs=list_tabs, env={},
                candidate_ports=[9225])

    def test_public_web_rejected(self) -> None:
        with self.assertRaises(ValueError):
            find_verified_channel_endpoint("public_web", list_tabs=lambda ep: [], env={})


if __name__ == "__main__":
    unittest.main()
