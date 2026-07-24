"""단위1 — 엔진별 모델 선택 파싱 (사장님 /st: Codex·Claude 모델 선택 Spec).

goal: docs/engineering/discord-deterministic-routing-login-first-goal-2026-07-24.md
엔진(agent) 선택은 fleet_args.py:179 에서 이미 codex|claude 로 검증된다(GREEN).
이 단위는 그 위에 **model** 선택을 얹는다 — 결정적(화이트리스트/fail-closed),
새 필드를 조용히 무시하거나 임의 문자열을 통과시키지 않는다.
"""

from __future__ import annotations

import unittest

from tools.multi_position_sourcing.fleet_args import parse_fleet_args, FleetArgsError

CU = "https://app.clickup.com/t/86exwz89j"


class ModelParamParsing(unittest.TestCase):
    def test_model_captured_into_params(self):
        got = parse_fleet_args(
            "fleet-run", f"aisearch {CU} agent:claude model:claude-sonnet-5"
        )
        self.assertEqual((got.get("params") or {}).get("model"), "claude-sonnet-5")

    def test_empty_model_rejected_fail_closed(self):
        # agent 와 동일하게, 빈 문자열도 이상값으로 명시 거부(조용히 미지정 금지).
        with self.assertRaises(FleetArgsError):
            parse_fleet_args("fleet-run", f"aisearch {CU} agent:claude model:")

    def test_overlong_model_rejected(self):
        with self.assertRaises(FleetArgsError):
            parse_fleet_args(
                "fleet-run", f"aisearch {CU} agent:claude model:{'x' * 100}"
            )


if __name__ == "__main__":
    unittest.main()
