"""채널별 CDP endpoint 해석 (TODO-2b 조각 A) — portal_browsers.sh 포트 정합.

계약: resolve_channel_cdp_endpoint(channel, *, value, env)
우선순위: value(http) > 전역 env > 채널별 포트 env > 채널 기본 포트(9223/9224/9225).
public_web 은 CDP 대상 아님 → ValueError. 기본 포트·env 이름은 portal_browsers.sh 와 동일.
"""

from __future__ import annotations

import unittest

from tools.multi_position_sourcing.portal_worker import (
    PortalWorker,
    PortalWorkerConfig,
    resolve_channel_cdp_endpoint,
)


class ResolveChannelCdpEndpointTests(unittest.TestCase):
    def test_channel_default_ports_match_portal_browsers_sh(self) -> None:
        self.assertEqual(resolve_channel_cdp_endpoint("saramin", env={}), "http://127.0.0.1:9223")
        self.assertEqual(resolve_channel_cdp_endpoint("jobkorea", env={}), "http://127.0.0.1:9224")
        self.assertEqual(resolve_channel_cdp_endpoint("linkedin_rps", env={}), "http://127.0.0.1:9225")

    def test_channel_port_env_override(self) -> None:
        self.assertEqual(
            resolve_channel_cdp_endpoint("saramin", env={"SARAMIN_PORT": "19223"}),
            "http://127.0.0.1:19223",
        )
        self.assertEqual(
            resolve_channel_cdp_endpoint("jobkorea", env={"JOBKOREA_PORT": "19224"}),
            "http://127.0.0.1:19224",
        )

    def test_global_env_wins_over_channel_port(self) -> None:
        env = {"VALUEHIRE_PORTAL_CHROME_CDP_ENDPOINT": "http://global:1", "SARAMIN_PORT": "19223"}
        self.assertEqual(resolve_channel_cdp_endpoint("saramin", env=env), "http://global:1")

    def test_explicit_value_wins_over_global_env(self) -> None:
        env = {"VALUEHIRE_PORTAL_CHROME_CDP_ENDPOINT": "http://global:1"}
        self.assertEqual(
            resolve_channel_cdp_endpoint("saramin", value="http://y:2", env=env),
            "http://y:2",
        )

    def test_linkedin_port_env_override(self) -> None:
        # V1 반례: LINKEDIN_PORT 매핑 미검증 — 이름을 틀리게 바꿔도 통과하던 구멍 봉인.
        self.assertEqual(
            resolve_channel_cdp_endpoint("linkedin_rps", env={"LINKEDIN_PORT": "19225"}),
            "http://127.0.0.1:19225",
        )

    def test_out_of_range_port_falls_back_to_default(self) -> None:
        # V1 반례: isdigit() 만으론 0·65536 같은 무효 포트가 통과 → 1..65535 검증.
        for bad in ("0", "65536", "99999"):
            self.assertEqual(
                resolve_channel_cdp_endpoint("saramin", env={"SARAMIN_PORT": bad}),
                "http://127.0.0.1:9223",
                f"무효 포트 {bad} 는 채널 기본으로 폴백해야",
            )
        # 경계: 1·65535 는 유효
        self.assertEqual(
            resolve_channel_cdp_endpoint("saramin", env={"SARAMIN_PORT": "65535"}),
            "http://127.0.0.1:65535",
        )

    def test_public_web_is_not_a_cdp_channel(self) -> None:
        with self.assertRaises(ValueError):
            resolve_channel_cdp_endpoint("public_web", env={})

    def test_garbage_port_env_falls_back_to_default(self) -> None:
        # counter-AC: 비URL·비숫자 포트여도 크래시 없이 채널 기본으로 폴백.
        self.assertEqual(
            resolve_channel_cdp_endpoint("saramin", env={"SARAMIN_PORT": "not-a-port"}),
            "http://127.0.0.1:9223",
        )

    def test_fullwidth_digit_port_falls_back_to_default(self) -> None:
        # V2 반례 N1: 전각 숫자('９２２３')는 str.isdigit()==True 라 통과하지만 URL 에 그대로
        # 박혀 깨진 endpoint 를 만든다. ASCII 숫자만 유효 포트로 인정해야 한다(counter-AC 봉인).
        self.assertEqual(
            resolve_channel_cdp_endpoint("saramin", env={"SARAMIN_PORT": "９２２３"}),
            "http://127.0.0.1:9223",
        )

    def test_non_http_global_env_is_ignored(self) -> None:
        # 전역 env 가 http 로 시작 안 하면 무시하고 채널 기본으로.
        self.assertEqual(
            resolve_channel_cdp_endpoint("jobkorea", env={"VALUEHIRE_PORTAL_CHROME_CDP_ENDPOINT": "  "}),
            "http://127.0.0.1:9224",
        )


class WorkerCdpEndpointWiringTests(unittest.TestCase):
    """배선(R4·고아 해소): 워커의 CDP endpoint 해석이 resolve_channel_cdp_endpoint 를
    실제로 통과한다 — 순수 함수를 프로덕션 경로(start())에 연결해 고아를 없앤다.
    linkedin_rps 는 이미 connect_over_cdp 로 붙으므로 이 경로만 배선하고(동작 보존:
    명시 config 값이 값-우선으로 그대로 이김), 사람인·잡코리아 실이전은 조각 B(라이브)."""

    def test_worker_cdp_endpoint_preserves_explicit_config_value(self) -> None:
        cfg = PortalWorkerConfig(
            channel="linkedin_rps", chrome_cdp_endpoint="http://127.0.0.1:7777")
        w = PortalWorker(cfg, playwright=object())
        self.assertEqual(w._cdp_endpoint(), "http://127.0.0.1:7777")

    def test_worker_cdp_endpoint_falls_back_to_channel_port_when_value_empty(self) -> None:
        # config 값이 비면 채널 기본 포트(linkedin=9225)로 — 채널 인지가 실제 작동함을 증명.
        cfg = PortalWorkerConfig(channel="linkedin_rps", chrome_cdp_endpoint="")
        w = PortalWorker(cfg, playwright=object())
        self.assertEqual(
            w._cdp_endpoint(env={}), "http://127.0.0.1:9225")


if __name__ == "__main__":
    unittest.main()
