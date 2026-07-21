"""디스코드 직결 수신기 조각 A — envelope + 순수 수신 로직 (goal: docs/prompts/discord-direct-connect-goal-2026-07-17.md §5A).

인수 기준(기계 단언):
- /fleet-run envelope 1건 → dispatch_fleet_command 정확히 1회 + 응답문(잡 번호 포함).
- 파싱(parse_fleet_args, AC-1 이사)·권한검사(route_discord_invocation)는 경로당 정확히 1회(INV-D3).
- 비인가 사용자·신원미상 → 응답 None(침묵) + 감사 이벤트만(INV-D6). 큐 접촉 0.
- 길드 컨텍스트 보존: guild_id/channel_id/role_ids 가 DiscordInvocation 까지 그대로 전달
  (기존 hermes_fleet_bridge 의 DM 고정 재사용 금지 — goal §3).
- 검색 명령 인자 파싱 실패(따옴표 안 닫힘 등) → fail-closed: 인가자에겐 안전한 안내문,
  비인가자에겐 침묵. 원본 예외 문자열 비노출.
- 수신기는 네트워크를 직접 만지지 않는다(큐·감사·시계 전부 주입, INV-D1).
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from tools.multi_position_sourcing import direct_receiver as dr
from tools.multi_position_sourcing import fleet_dispatch
from tools.multi_position_sourcing.access import DiscordAuthorizedUser
from tools.multi_position_sourcing.direct_receiver import (
    DiscordEnvelope,
    handle_envelope,
)
from tools.multi_position_sourcing.discord_routing import DiscordAccessConfig

OWNER_ID = "814353841088757800"
MEMBER_ID = "222222222222222222"
STRANGER_ID = "999999999999999999"
CLICKUP_URL = "https://app.clickup.com/t/86eznizpq"

# INV-D1 기계 강제: 수신기 소스에 실행·동적로딩 원시요소가 없어야 한다.
# 허용 import 는 정확한 전체 경로로만 매칭한다(끝 이름만 보고 통과시키지 않음 — V1 재공격).
_ALLOWED_ABSOLUTE_IMPORTS = frozenset({
    "__future__", "re", "time", "dataclasses", "typing",
})
# 패키지 상대 import 는 레벨 1(같은 패키지) + 정확한 모듈명만(하위 경로 금지).
_ALLOWED_RELATIVE_MODULES = frozenset({
    "access", "discord_routing", "fleet_dispatch", "fleet_args",  # AC-1: 파싱 이사(hermes_fleet_bridge 제외)
})
# 맨 이름(builtin)으로 나타나면 안 되는 식별자 — __import__ 를 변수에 담아 나중에
# 부르는 우회(V1 재공격)까지 이름 존재 자체로 막는다. re.compile 처럼 안전한
# 표준 라이브러리 메서드와 충돌하지 않도록 '이름' 노드에만 적용한다.
_BANNED_NAMES = frozenset({
    "__import__", "eval", "exec", "compile", "getattr", "globals", "vars", "__loader__",
})
# 속성 접근(x.method)으로 나타나면 안 되는 위험 메서드 — 표준 안전 메서드
# (re.compile 등)와 겹치지 않는 실행·동적로딩 전용 이름 + introspection 탈출 도구.
# 후자(__dict__/__builtins__/__subclasses__ 등)는 허용 모듈 내부를 뒤져 __import__ 를
# 꺼내는 우회(V1 4차)를 막는다 — 정상 코드는 이 던더들을 만질 이유가 없다.
_BANNED_ATTRS = frozenset({
    "system", "popen", "Popen", "spawn", "import_module", "__import__", "check_output",
    "call", "run", "getoutput",
    "__dict__", "__builtins__", "__globals__", "__class__", "__subclasses__",
    "__bases__", "__mro__", "__loader__", "__getattribute__",
})


def execution_primitive_violations(source: str) -> list[str]:
    """AST 로 INV-D1 위반(허용 밖 import·금지 식별자)을 모두 수집한다.

    문자열 매칭이 아니라 구조(import 노드·이름 노드)를 본다 — 별칭·동적 조합·하위
    경로 우회를 전부 잡는다. 우회하려면 결국 import 나 금지 이름 참조가 필요하고,
    둘 다 AST 에 반드시 드러난다.
    """
    import ast

    violations: list[str] = []
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                # 하위 모듈(re._compiler 등)은 정확한 전체 이름이 허용목록에 있어야
                # 통과 — 허용 최상위 이름 뒤에 점을 붙인 우회(V1 4차)를 막는다.
                if alias.name not in _ALLOWED_ABSOLUTE_IMPORTS:
                    violations.append(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # 상대 import: 레벨 1 + 정확한 모듈명만(하위 경로 금지)
                if node.level != 1 or (node.module or "") not in _ALLOWED_RELATIVE_MODULES:
                    # from . import X 는 module=None → 별칭이 허용 모듈명이어야
                    if node.module is None and all(
                            a.name in _ALLOWED_RELATIVE_MODULES for a in node.names):
                        continue
                    violations.append(f"from {'.' * node.level}{node.module or ''} import ...")
            elif (node.module or "").split(".")[0] not in _ALLOWED_ABSOLUTE_IMPORTS:
                violations.append(f"from {node.module} import ...")
        elif isinstance(node, ast.Name):
            if node.id in _BANNED_NAMES:
                violations.append(f"name:{node.id}")
        elif isinstance(node, ast.Attribute):
            if node.attr in _BANNED_ATTRS:
                violations.append(f"attr:{node.attr}")
    return violations

AUTHORIZED = (
    DiscordAuthorizedUser(name="owner", alias="o", email="o@valueconnect.kr", discord_id=OWNER_ID),
    DiscordAuthorizedUser(name="member", alias="m", email="m@valueconnect.kr", discord_id=MEMBER_ID),
)


class FakeQueue:
    """enqueue 만 기록하는 가짜 큐 — 네트워크 0."""

    def __init__(self) -> None:
        self.enqueued: list[dict] = []

    def enqueue(self, payload: dict) -> dict:
        self.enqueued.append(payload)
        return {"id": 77, **payload}

    def recent(self, n: int) -> list[dict]:
        return []


def _dm_envelope(user_id: str = OWNER_ID, *, command: str = "fleet-run",
                 raw_args: str = CLICKUP_URL, event_id: str = "111111111111111111") -> DiscordEnvelope:
    return DiscordEnvelope(
        event_id=event_id, user_id=user_id, channel_id="333333333333333333",
        command=command, raw_args=raw_args, is_dm=True,
    )


class _NotifySilencedCase(unittest.TestCase):
    """enqueue 에 도달하는 테스트는 워커의 직접 Discord 알림을 반드시 끈다.

    실자격증명이 보이는 로컬 환경에서 dispatch_fleet_command → discord_notify 가
    실발송하는 사고 방지(알림 주입 분리 자체는 goal 조각 F 범위).
    """

    def setUp(self) -> None:
        from tools.multi_position_sourcing import fleet_worker
        patcher = patch.object(fleet_worker, "discord_notify", lambda job, text: None)
        patcher.start()
        self.addCleanup(patcher.stop)


class FleetRunDispatchTests(_NotifySilencedCase):
    def test_fleet_run_dispatches_once_and_replies_with_job_id(self) -> None:
        queue = FakeQueue()
        audit: list[dict] = []
        with patch.object(dr, "parse_fleet_args",
                          side_effect=dr.parse_fleet_args) as parse_spy, \
             patch.object(fleet_dispatch, "route_discord_invocation",
                          side_effect=fleet_dispatch.route_discord_invocation) as route_spy, \
             patch.object(dr, "dispatch_fleet_command",
                          side_effect=dr.dispatch_fleet_command) as dispatch_spy:
            result = handle_envelope(
                _dm_envelope(), queue=queue, authorized_users=AUTHORIZED,
                config=DiscordAccessConfig(allow_dm=True), audit=audit.append,
            )
        self.assertTrue(result["handled"])
        self.assertEqual(result["action"], "enqueued")
        self.assertEqual(len(queue.enqueued), 1)
        self.assertIn("77", result["response"], "응답문에 잡 번호가 있어야 한다")
        # INV-D3: 파싱·권한검사·디스패치 경로당 정확히 1회
        self.assertEqual(parse_spy.call_count, 1)
        self.assertEqual(route_spy.call_count, 1)
        self.assertEqual(dispatch_spy.call_count, 1)
        self.assertTrue(any(e.get("action") == "enqueued" for e in audit))

    def test_receiver_never_executes_itself_enqueue_only(self) -> None:
        # INV-D1: 수신기는 응답문 생성까지만 — 큐에 넣은 payload 는 기존 계약 그대로.
        queue = FakeQueue()
        handle_envelope(_dm_envelope(), queue=queue, authorized_users=AUTHORIZED,
                        config=DiscordAccessConfig(allow_dm=True))
        self.assertEqual(len(queue.enqueued), 1)
        payload = queue.enqueued[0]
        self.assertEqual(payload["status"], "queued")
        self.assertIn(payload["skill"], ("humansearch", "aisearch", "url"))


class FailClosedTests(unittest.TestCase):
    def test_unauthorized_user_gets_silence_and_audit_only(self) -> None:
        queue = FakeQueue()
        audit: list[dict] = []
        result = handle_envelope(
            _dm_envelope(STRANGER_ID), queue=queue, authorized_users=AUTHORIZED,
            config=DiscordAccessConfig(allow_dm=True), audit=audit.append,
        )
        self.assertIsNone(result["response"], "비인가자에겐 무응답(침묵)이어야 한다")
        self.assertEqual(queue.enqueued, [])
        self.assertTrue(any(e.get("action") == "denied" for e in audit),
                        "감사 로그에는 남아야 한다")

    def test_missing_identity_is_ignored_without_queue_touch(self) -> None:
        queue = FakeQueue()
        audit: list[dict] = []
        for bad in ("", "   ", "abc"):  # snowflake 모양 아님 = 신원 불신
            result = handle_envelope(
                _dm_envelope(bad), queue=queue, authorized_users=AUTHORIZED,
                config=DiscordAccessConfig(allow_dm=True), audit=audit.append,
            )
            self.assertIsNone(result["response"], bad)
        self.assertEqual(queue.enqueued, [])
        self.assertTrue(audit, "신원미상도 감사 이벤트는 남긴다")

    def test_malformed_identity_rejected_even_with_allowed_role(self) -> None:
        # 신원 게이트의 실질 방어선: 역할이 allowlist 에 걸려도 user_id 가
        # snowflake 꼴이 아니면(게이트웨이 버그·위조 신호) 무조건 무시한다.
        # DM 경로는 하위 연락처 대조가 겹으로 막지만, 길드 역할 인증은
        # user_id 모양과 무관하게 통과시키므로 이 게이트가 없으면 뚫린다.
        queue = FakeQueue()
        config = DiscordAccessConfig(
            allowed_channel_ids=("555555555555555555",),
            allowed_role_ids=("777777777777777777",),
        )
        result = handle_envelope(
            DiscordEnvelope(
                event_id="444444444444444444", user_id="not-a-snowflake",
                channel_id="555555555555555555", guild_id="666666666666666666",
                role_ids=("777777777777777777",), command="fleet-run",
                raw_args=CLICKUP_URL, is_dm=False,
            ),
            queue=queue, authorized_users=AUTHORIZED, config=config,
        )
        self.assertIsNone(result["response"])
        self.assertEqual(result["action"], "ignored_identity")
        self.assertEqual(queue.enqueued, [])

    def test_parse_error_is_fail_closed_and_does_not_leak(self) -> None:
        queue = FakeQueue()
        # 인가자: 안전한 안내문(원본 셸 파싱 예외 원문 비노출), 큐 접촉 0.
        result = handle_envelope(
            _dm_envelope(raw_args='url:"unclosed'), queue=queue,
            authorized_users=AUTHORIZED, config=DiscordAccessConfig(allow_dm=True),
        )
        self.assertIsNotNone(result["response"])
        self.assertNotIn("Traceback", result["response"])
        self.assertNotIn("shlex", result["response"])
        self.assertEqual(queue.enqueued, [])
        # 비인가자: 파싱 실패라도 침묵(오류문으로 명령 존재를 알려주지 않는다).
        result2 = handle_envelope(
            _dm_envelope(STRANGER_ID, raw_args='url:"unclosed'), queue=queue,
            authorized_users=AUTHORIZED, config=DiscordAccessConfig(allow_dm=True),
        )
        self.assertIsNone(result2["response"])
        self.assertEqual(queue.enqueued, [])

    def test_control_characters_in_args_fail_closed(self) -> None:
        queue = FakeQueue()
        result = handle_envelope(
            _dm_envelope(raw_args="https://app.clickup.com/t/a b"), queue=queue,
            authorized_users=AUTHORIZED, config=DiscordAccessConfig(allow_dm=True),
        )
        self.assertNotEqual(result["action"], "enqueued")
        self.assertEqual(queue.enqueued, [])


class GuildContextTests(_NotifySilencedCase):
    """goal §3 — 직결 수신기는 길드 컨텍스트를 처음으로 진짜 전달한다(DM 고정 금지)."""

    def _guild_envelope(self, **overrides) -> DiscordEnvelope:
        fields = dict(
            event_id="444444444444444444", user_id=STRANGER_ID,
            channel_id="555555555555555555", guild_id="666666666666666666",
            role_ids=("777777777777777777",), command="fleet-run",
            raw_args=CLICKUP_URL, is_dm=False,
        )
        fields.update(overrides)
        return DiscordEnvelope(**fields)

    def test_guild_fields_reach_invocation_unchanged(self) -> None:
        queue = FakeQueue()
        seen: list = []

        def capture(invocation, **kwargs):
            seen.append(invocation)
            return fleet_dispatch.dispatch_fleet_command(invocation, **kwargs)

        config = DiscordAccessConfig(
            allowed_channel_ids=("555555555555555555",),
            allowed_role_ids=("777777777777777777",),
        )
        with patch.object(dr, "dispatch_fleet_command", side_effect=capture):
            result = handle_envelope(
                self._guild_envelope(), queue=queue,
                authorized_users=AUTHORIZED, config=config,
            )
        self.assertEqual(result["action"], "enqueued", "역할 허용 → 등록돼야 한다")
        inv = seen[0]
        self.assertFalse(inv.is_dm, "DM 고정(hermes 어댑터 재사용) 금지")
        self.assertEqual(inv.guild_id, "666666666666666666")
        self.assertEqual(inv.channel_id, "555555555555555555")
        self.assertEqual(inv.member_role_ids, ("777777777777777777",))

    def test_guild_channel_not_allowlisted_is_silent(self) -> None:
        queue = FakeQueue()
        audit: list[dict] = []
        config = DiscordAccessConfig(allowed_channel_ids=("123456789012345678",))
        result = handle_envelope(
            self._guild_envelope(), queue=queue,
            authorized_users=AUTHORIZED, config=config, audit=audit.append,
        )
        self.assertIsNone(result["response"])
        self.assertEqual(queue.enqueued, [])
        self.assertTrue(any(e.get("action") == "denied" for e in audit))


class SecretNonExposureTests(unittest.TestCase):
    def test_queue_exception_never_leaks_raw_error_text(self) -> None:
        # goal §6-4: 예외 메시지에 토큰 모양 문자열 → 회신에 원문 부재(INV-D5).
        class ExplodingQueue(FakeQueue):
            def enqueue(self, payload: dict) -> dict:
                raise RuntimeError("Bearer sk-SECRET-TOKEN-12345 rejected")

        audit: list[dict] = []
        result = handle_envelope(
            _dm_envelope(), queue=ExplodingQueue(), authorized_users=AUTHORIZED,
            config=DiscordAccessConfig(allow_dm=True), audit=audit.append,
        )
        self.assertEqual(result["action"], "internal_error")
        combined = (result["response"] or "") + result["reason"] + repr(audit)
        self.assertNotIn("SECRET", combined, "raw 예외 원문이 어디에도 새면 안 된다")


class V1SealTests(unittest.TestCase):
    """Codex V1 반례 6건 봉인 (2026-07-18)."""

    def test_parse_error_response_never_echoes_user_input(self) -> None:
        # C2: 형식 오류 응답에 사용자 입력 원문(비밀 모양·멘션 폭탄) 에코 금지(INV-D5).
        queue = FakeQueue()
        for raw in (
            'url:"sk-SECRET-999 @everyone',   # 따옴표 오류(셸 파서 메시지)
            "@everyone sk-SECRET-999",        # 맨 토큰 거부(토큰 repr 에코 경로)
            "badfield:sk-SECRET-999",         # 허용 안 된 필드(키 에코 경로)
        ):
            result = handle_envelope(
                _dm_envelope(raw_args=raw), queue=queue,
                authorized_users=AUTHORIZED, config=DiscordAccessConfig(allow_dm=True),
            )
            self.assertIsNotNone(result["response"], raw)
            self.assertNotIn("sk-SECRET-999", result["response"], raw)
            self.assertNotIn("@everyone", result["response"], raw)
            self.assertNotIn("badfield", result["response"], raw)
            self.assertLess(len(result["response"]), 300, "회신은 짧은 안내문이어야 한다")
        self.assertEqual(queue.enqueued, [])

    def test_audit_callback_exception_never_kills_receiver(self) -> None:
        # C3: 감사 콜백이 죽어도 수신기는 죽지 않는다(fail-soft 감사, 처리 우선).
        def broken_audit(event: dict) -> None:
            raise RuntimeError("disk full")

        queue = FakeQueue()
        for env in (
            _dm_envelope(),                                   # 성공 경로
            _dm_envelope(STRANGER_ID),                        # 침묵 경로
            _dm_envelope(raw_args='url:"unclosed'),           # 파싱 실패 경로
        ):
            result = handle_envelope(
                env, queue=queue, authorized_users=AUTHORIZED,
                config=DiscordAccessConfig(allow_dm=True), audit=broken_audit,
            )
            self.assertTrue(result["handled"])

    def test_dm_flag_with_guild_context_is_inconsistent_and_silent(self) -> None:
        # C4: is_dm=True 로 위조된 길드 이벤트가 길드 allowlist 를 우회하지 못한다.
        queue = FakeQueue()
        audit: list[dict] = []
        result = handle_envelope(
            DiscordEnvelope(
                event_id="444444444444444444", user_id=MEMBER_ID,
                channel_id="555555555555555555", guild_id="666666666666666666",
                command="fleet-run", raw_args=CLICKUP_URL, is_dm=True,
            ),
            queue=queue, authorized_users=AUTHORIZED,
            config=DiscordAccessConfig(allow_dm=True), audit=audit.append,
        )
        self.assertIsNone(result["response"])
        self.assertEqual(queue.enqueued, [])
        self.assertTrue(any(e.get("action") == "ignored_inconsistent" for e in audit))

    def test_blank_event_id_fails_closed(self) -> None:
        # C5: event_id 는 감사·멱등키의 뿌리 — snowflake 꼴 아니면 처리 자체를 거부.
        queue = FakeQueue()
        for bad in ("", "  ", "abc"):
            result = handle_envelope(
                _dm_envelope(event_id=bad), queue=queue,
                authorized_users=AUTHORIZED, config=DiscordAccessConfig(allow_dm=True),
            )
            self.assertIsNone(result["response"], bad)
        self.assertEqual(queue.enqueued, [])

    def test_owner_only_parse_error_gives_member_owner_denial(self) -> None:
        # C1: owner 전용 명령은 형식이 틀려도 비owner 에겐 정상 경로와 같은 안내
        # (형식 오류 응답으로 경로별 판정이 갈라지지 않게 일관화).
        queue = FakeQueue()
        result = handle_envelope(
            _dm_envelope(MEMBER_ID, command="fleet-cancel", raw_args='job:"broken'),
            queue=queue, authorized_users=AUTHORIZED,
            config=DiscordAccessConfig(allow_dm=True),
        )
        self.assertIsNotNone(result["response"])
        self.assertIn("owner", result["response"])
        self.assertNotIn("형식", result["response"], "형식 힌트로 경로가 갈라지면 안 된다")

    def test_receiver_source_has_no_execution_primitives(self) -> None:
        # C6/INV-D1: 실제 수신기 소스는 위반 0(enqueue-only 기계 강제).
        import inspect
        self.assertEqual(execution_primitive_violations(inspect.getsource(dr)), [])

    def test_execution_guard_catches_every_known_bypass(self) -> None:
        # V1 3회차까지의 모든 우회 패턴을 합성 소스로 재현 — 검사기 자체가
        # 이들을 전부 잡는지 봉인한다(검사기가 우회되면 C6 계약이 무의미).
        bypasses = {
            "direct_subprocess": "import subprocess\n",
            "alias_os_system": "from os import system as launch\n",
            "dynamic_importlib": "import importlib\nx = importlib.import_module('sub'+'process')\n",
            "stored_dunder_import": "f = __import__\nm = f('os')\n",
            "subpath_ending_allowed": "from .unapproved.access import x\n",
            "deep_relative": "from ..other.thing import y\n",
            "getattr_reach": "import os\ng = getattr(os, 'sys'+'tem')\n",
            "eval_call": "y = eval('1+1')\n",
            "dunder_dig_dict": "imp = re.__dict__['__buil'+'tins__']['__imp'+'ort__']\n",
            "submodule_of_allowed": "import re._compiler\n",
            "subclasses_escape": "obj = ().__class__.__bases__[0].__subclasses__()\n",
        }
        for name, src in bypasses.items():
            self.assertNotEqual(
                execution_primitive_violations(src), [],
                f"우회 미탐지: {name} — {src!r}")

    def test_execution_guard_allows_legitimate_imports(self) -> None:
        # 과탐 방지: 실제 수신기가 쓰는 정상 import 는 통과해야 한다(검사기가
        # 모든 걸 막아서 우연히 GREEN 되는 가짜 봉인이 아님을 증명).
        ok = (
            "from __future__ import annotations\n"
            "import re\nimport time\n"
            "from dataclasses import dataclass\n"
            "from typing import Any\n"
            "from .access import DiscordAuthorizedUser\n"
            "from .fleet_dispatch import dispatch_fleet_command, is_owner\n"
            "from . import fleet_dispatch\n"
        )
        self.assertEqual(execution_primitive_violations(ok), [])

    def test_integer_typed_identity_fields_fail_closed(self) -> None:
        # V1 재공격 item5 봉인: 게이트웨이 버그·위조로 int 가 흘러들어와도
        # str 강제변환으로 통과시키지 않는다 — 타입까지 fail-closed.
        queue = FakeQueue()
        config = DiscordAccessConfig(
            allowed_channel_ids=("555555555555555555",),
            allowed_role_ids=("777777777777777777",),
        )
        int_event = DiscordEnvelope(
            event_id=444444444444444444, user_id=OWNER_ID,  # type: ignore[arg-type]
            channel_id="333333333333333333", command="fleet-run",
            raw_args=CLICKUP_URL, is_dm=True,
        )
        int_role = DiscordEnvelope(
            event_id="444444444444444444", user_id=STRANGER_ID,
            channel_id="555555555555555555", guild_id="666666666666666666",
            role_ids=(777777777777777777,),  # type: ignore[arg-type]
            command="fleet-run", raw_args=CLICKUP_URL, is_dm=False,
        )
        int_user = DiscordEnvelope(
            event_id="444444444444444444", user_id=814353841088757800,  # type: ignore[arg-type]
            channel_id="333333333333333333", command="fleet-run",
            raw_args=CLICKUP_URL, is_dm=True,
        )
        for env in (int_event, int_role, int_user):
            result = handle_envelope(
                env, queue=queue, authorized_users=AUTHORIZED, config=config)
            self.assertIsNone(result["response"])
        self.assertEqual(queue.enqueued, [])

    def test_audit_failure_is_visible_in_result(self) -> None:
        # V1 재공격 new_issue 봉인: 감사 유실이 조용히 사라지지 않는다 —
        # 게이트웨이가 경보를 올릴 수 있게 결과에 표시.
        def broken_audit(event: dict) -> None:
            raise RuntimeError("disk full")

        queue = FakeQueue()
        result = handle_envelope(
            _dm_envelope(), queue=queue, authorized_users=AUTHORIZED,
            config=DiscordAccessConfig(allow_dm=True), audit=broken_audit,
        )
        self.assertTrue(result.get("audit_failed"), "감사 실패가 결과에 드러나야 한다")
        ok = handle_envelope(
            _dm_envelope(), queue=queue, authorized_users=AUTHORIZED,
            config=DiscordAccessConfig(allow_dm=True), audit=lambda e: None,
        )
        self.assertFalse(ok.get("audit_failed"))


class MemberOwnerBoundaryTests(unittest.TestCase):
    def test_member_owner_only_command_gets_polite_denial_not_silence(self) -> None:
        # 인가된 멤버가 owner 전용(fleet-cancel)을 부르면 — 신원은 믿으므로 침묵이 아니라 안내.
        queue = FakeQueue()
        result = handle_envelope(
            _dm_envelope(MEMBER_ID, command="fleet-cancel", raw_args="job:3"),
            queue=queue, authorized_users=AUTHORIZED,
            config=DiscordAccessConfig(allow_dm=True),
        )
        self.assertIsNotNone(result["response"])
        self.assertIn("owner", result["response"])
        self.assertEqual(queue.enqueued, [])


if __name__ == "__main__":
    unittest.main()
