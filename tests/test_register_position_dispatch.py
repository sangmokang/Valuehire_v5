from __future__ import annotations

import unittest

from tools.multi_position_sourcing.access import DiscordAuthorizedUser
from tools.multi_position_sourcing.discord_routing import (
    DiscordAccessConfig,
    DiscordInvocation,
)
from tools.multi_position_sourcing.position_registration import (
    FY26_CLIENTS_POSITION_LIST_ID,
    run_position_registration,
)
from tools.multi_position_sourcing.register_position_dispatch import (
    dispatch_register_position,
)

# PC-A3 — register-position Discord 디스패처. 인가 통과 payload → run_position_registration
# 정확히 1회, external_posting_sent=False(SOT3). 인가/타명령/무포지션은 디스패치 없음.

_OWNER_ID = "814353841088757800"
OWNER = DiscordAuthorizedUser(name="Owner", alias="owner", email="o@x.com", discord_id=_OWNER_ID)
DM_CONFIG = DiscordAccessConfig(allow_dm=True)

LONG_JD = (
    "회사소개\nAcme는 핀테크 스타트업입니다.\n"
    "주요업무\n- 백엔드 API 설계 및 구현\n담당업무\n- 대규모 분산 시스템 운영\n"
    "자격요건\n- Python 3년 이상\n- 분산 시스템 경험\n우대사항\n- Kubernetes 경험\n"
    "responsibilities requirements qualifications 채용 포지션"
)


def _invocation(*, user_id=_OWNER_ID, command_name="register-position", options=None, is_dm=True):
    return DiscordInvocation(
        user_id=user_id,
        channel_id="",
        command_name=command_name,
        is_dm=is_dm,
        invocation_kind="slash",
        guild_id="",
        member_role_ids=(),
        options=options or {},
    )


def _spy_registration():
    calls: list = []

    def spy(parse_result, **kwargs):
        calls.append((parse_result, kwargs))
        return run_position_registration(parse_result, **kwargs)

    spy.calls = calls  # type: ignore[attr-defined]
    return spy


class RegisterPositionDispatchTests(unittest.TestCase):
    def test_authorized_register_position_dispatches_exactly_once(self) -> None:
        spy = _spy_registration()
        outcome = dispatch_register_position(
            _invocation(options={"text": LONG_JD}),
            authorized_users=[OWNER],
            config=DM_CONFIG,
            register_position=spy,
        )
        self.assertEqual(len(spy.calls), 1)  # type: ignore[attr-defined]
        self.assertIsNotNone(outcome)
        self.assertFalse(outcome.external_posting_sent)  # SOT3
        self.assertFalse(outcome.secret_emitted)
        # 목적지 기본이 FY26ClientsPosition 로 전달됨(PC-A1 배선 재사용).
        _parse_result, kwargs = spy.calls[0]  # type: ignore[attr-defined]
        self.assertEqual(kwargs.get("clickup_list_id"), FY26_CLIENTS_POSITION_LIST_ID)

    def test_unauthorized_user_does_not_dispatch(self) -> None:
        spy = _spy_registration()
        outcome = dispatch_register_position(
            _invocation(user_id="999999999999999999", options={"text": LONG_JD}),
            authorized_users=[OWNER],
            config=DM_CONFIG,
            register_position=spy,
        )
        self.assertIsNone(outcome)
        self.assertEqual(len(spy.calls), 0)  # type: ignore[attr-defined]

    def test_wrong_command_does_not_dispatch(self) -> None:
        spy = _spy_registration()
        outcome = dispatch_register_position(
            _invocation(command_name="run-search", options={"text": LONG_JD}),
            authorized_users=[OWNER],
            config=DM_CONFIG,
            register_position=spy,
        )
        self.assertIsNone(outcome)
        self.assertEqual(len(spy.calls), 0)  # type: ignore[attr-defined]

    def test_missing_position_does_not_dispatch(self) -> None:
        spy = _spy_registration()
        outcome = dispatch_register_position(
            _invocation(options={}),
            authorized_users=[OWNER],
            config=DM_CONFIG,
            register_position=spy,
        )
        self.assertIsNone(outcome)
        self.assertEqual(len(spy.calls), 0)  # type: ignore[attr-defined]

    def test_url_option_routes_to_registration(self) -> None:
        # url 옵션도 등록 파서가 인식하는 메시지로 조립돼 디스패치된다(발송 없음).
        spy = _spy_registration()
        outcome = dispatch_register_position(
            _invocation(options={"url": "https://www.wanted.co.kr/wd/363433"}),
            authorized_users=[OWNER],
            config=DM_CONFIG,
            register_position=spy,
        )
        self.assertEqual(len(spy.calls), 1)  # type: ignore[attr-defined]
        self.assertIsNotNone(outcome)
        self.assertFalse(outcome.external_posting_sent)


if __name__ == "__main__":
    unittest.main()
