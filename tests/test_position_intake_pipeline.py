from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.multi_position_sourcing.posting_models import RegistrationOutcome
from tools.multi_position_sourcing.request_parser import (
    parse_discord_position_registration_request,
)


LONG_JD_BODY = """시니어 백엔드 엔지니어
회사소개
Acme는 B2B SaaS를 만드는 회사입니다.
주요업무
- 백엔드 API 설계 및 운영
- 데이터 파이프라인 운영
자격요건
- Python 5년 이상
- 분산 시스템 경험
우대사항
- Kubernetes 경험
채용 포지션 JD입니다.
"""


class PositionIntakeEmailTests(unittest.TestCase):
    def test_email_with_wanted_url_builds_registration_message(self) -> None:
        from tools.multi_position_sourcing.position_intake_email import (
            build_registration_message_from_email,
        )

        message = build_registration_message_from_email(
            "신규 포지션 전달드립니다",
            "안녕하세요. 채용공고 URL입니다: https://www.wanted.co.kr/wd/363433 확인 부탁드립니다.",
        )

        self.assertEqual(message, "포지션 등록 https://www.wanted.co.kr/wd/363433")
        parsed = parse_discord_position_registration_request(message)
        self.assertTrue(parsed.should_route_to_registration)
        self.assertEqual(parsed.input_kind, "wanted_url")

    def test_email_with_jd_body_builds_pasted_jd_registration_message(self) -> None:
        from tools.multi_position_sourcing.position_intake_email import (
            build_registration_message_from_email,
        )

        message = build_registration_message_from_email("JD 공유", LONG_JD_BODY)

        self.assertTrue(message.startswith("포지션 등록\n"))
        parsed = parse_discord_position_registration_request(message)
        self.assertTrue(parsed.should_route_to_registration)
        self.assertEqual(parsed.input_kind, "pasted_jd")
        self.assertIn("시니어 백엔드 엔지니어", parsed.text)

    def test_general_customer_email_is_fail_closed(self) -> None:
        from tools.multi_position_sourcing.position_intake_email import (
            build_registration_message_from_email,
        )

        message = build_registration_message_from_email(
            "다음 주 미팅 일정",
            "안녕하세요. 다음 주 화요일 2시에 미팅 가능하실까요? 채용 진행 현황도 그때 이야기 나누시죠.",
        )

        self.assertEqual(message, "")
        parsed = parse_discord_position_registration_request(message)
        self.assertFalse(parsed.should_route_to_registration)


class PositionFollowupQueueTests(unittest.TestCase):
    def test_successful_registration_enqueues_two_idempotent_followups(self) -> None:
        from tools.multi_position_sourcing.position_followups import (
            FOLLOWUP_TASKS,
            enqueue_position_followups,
            load_followup_queue,
        )

        with tempfile.TemporaryDirectory() as tmp:
            queue_path = Path(tmp) / "followups.json"
            outcome = RegistrationOutcome(
                status="created",
                is_new_task=True,
                reason="new position task created",
                task_id="86abc",
                task_url="https://app.clickup.com/t/86abc",
                dry_run=False,
            )

            first = enqueue_position_followups(outcome, queue_path=queue_path, now_iso="2026-07-05T00:00:00Z")
            second = enqueue_position_followups(outcome, queue_path=queue_path, now_iso="2026-07-05T00:01:00Z")
            queue = load_followup_queue(queue_path)

            self.assertEqual([item["task"] for item in first], list(FOLLOWUP_TASKS))
            self.assertEqual([item["task"] for item in second], list(FOLLOWUP_TASKS))
            self.assertEqual(len(queue), 2)
            self.assertEqual({item["task"] for item in queue}, set(FOLLOWUP_TASKS))
            self.assertEqual({item["position_key"] for item in queue}, {"clickup_task:86abc"})

            raw = json.loads(queue_path.read_text(encoding="utf-8"))
            self.assertEqual(raw["version"], 1)

    def test_failed_registration_does_not_create_followups(self) -> None:
        from tools.multi_position_sourcing.position_followups import (
            enqueue_position_followups,
            load_followup_queue,
        )

        with tempfile.TemporaryDirectory() as tmp:
            queue_path = Path(tmp) / "followups.json"
            outcome = RegistrationOutcome(
                status="skipped",
                is_new_task=False,
                reason="not a position registration request",
            )

            enqueued = enqueue_position_followups(outcome, queue_path=queue_path)

            self.assertEqual(enqueued, ())
            self.assertEqual(load_followup_queue(queue_path), [])
            self.assertFalse(queue_path.exists())

    def test_dry_run_registration_does_not_create_followups_even_with_task_id(self) -> None:
        from tools.multi_position_sourcing.position_followups import (
            enqueue_position_followups,
            load_followup_queue,
        )

        with tempfile.TemporaryDirectory() as tmp:
            queue_path = Path(tmp) / "followups.json"
            outcome = RegistrationOutcome(
                status="created",
                is_new_task=True,
                reason="new position task planned (dry-run)",
                task_id="86preview",
                task_url="https://app.clickup.com/t/86preview",
                dry_run=True,
            )

            enqueued = enqueue_position_followups(outcome, queue_path=queue_path)

            self.assertEqual(enqueued, ())
            self.assertEqual(load_followup_queue(queue_path), [])
            self.assertFalse(queue_path.exists())


class PositionIntakeRunnerTests(unittest.TestCase):
    def test_scheduled_tick_uses_fixed_gmail_query_and_requires_approval(self) -> None:
        from tools.multi_position_sourcing.position_intake_runner import (
            GMAIL_POSITION_INTAKE_QUERY,
            IntakeEmail,
            run_scheduled_position_intake,
        )

        seen_queries: list[str] = []
        register_calls: list[tuple[object, bool]] = []

        def search_threads(query: str):
            seen_queries.append(query)
            return (
                IntakeEmail(
                    message_id="msg-1",
                    subject="신규 포지션",
                    body=LONG_JD_BODY,
                    from_email="client@example.com",
                ),
            )

        def register_position(parse_result, **kwargs):
            register_calls.append((parse_result, kwargs["dry_run"]))
            return RegistrationOutcome(
                status="created",
                is_new_task=True,
                reason="preview",
                task_id="",
                dry_run=kwargs["dry_run"],
            )

        with tempfile.TemporaryDirectory() as tmp:
            result = run_scheduled_position_intake(
                search_threads=search_threads,
                register_position=register_position,
                queue_path=Path(tmp) / "followups.json",
                auto_registration_allowed=False,
                approved_message_ids=(),
            )

        self.assertEqual(seen_queries, [GMAIL_POSITION_INTAKE_QUERY])
        self.assertEqual(register_calls[0][1], True)
        self.assertEqual(result["events"][0]["status"], "approval_required")
        self.assertEqual(result["enqueued_count"], 0)

    def test_approved_tick_registers_and_enqueues_followups(self) -> None:
        from tools.multi_position_sourcing.position_followups import load_followup_queue
        from tools.multi_position_sourcing.position_intake_runner import (
            IntakeEmail,
            run_position_intake_tick,
        )

        register_calls: list[bool] = []

        def register_position(_parse_result, **kwargs):
            register_calls.append(kwargs["dry_run"])
            return RegistrationOutcome(
                status="created",
                is_new_task=True,
                reason="created",
                task_id="86approved",
                task_url="https://app.clickup.com/t/86approved",
                dry_run=kwargs["dry_run"],
            )

        with tempfile.TemporaryDirectory() as tmp:
            queue_path = Path(tmp) / "followups.json"
            result = run_position_intake_tick(
                emails=(
                    IntakeEmail(message_id="msg-approved", subject="JD 공유", body=LONG_JD_BODY),
                ),
                register_position=register_position,
                queue_path=queue_path,
                approved_message_ids=("msg-approved",),
                now_iso="2026-07-05T00:00:00Z",
            )
            queue = load_followup_queue(queue_path)

        self.assertEqual(register_calls, [False])
        self.assertEqual(result["events"][0]["status"], "registered")
        self.assertEqual(result["enqueued_count"], 2)
        self.assertEqual({item["task"] for item in queue}, {"url_presetting", "jd_set_build"})
        self.assertNotIn("send", json.dumps(queue, ensure_ascii=False).lower())

    def test_followup_drain_yields_when_owner_active(self) -> None:
        from tools.multi_position_sourcing.position_followups import enqueue_position_followups
        from tools.multi_position_sourcing.position_intake_runner import drain_position_followups

        with tempfile.TemporaryDirectory() as tmp:
            queue_path = Path(tmp) / "followups.json"
            enqueue_position_followups(
                RegistrationOutcome(
                    status="created",
                    is_new_task=True,
                    reason="created",
                    task_id="86yield",
                    task_url="https://app.clickup.com/t/86yield",
                    dry_run=False,
                ),
                queue_path=queue_path,
            )
            calls: list[dict] = []

            result = drain_position_followups(
                queue_path=queue_path,
                execute_followup=lambda item: calls.append(item),
                owner_activity_detected=True,
            )

        self.assertEqual(calls, [])
        self.assertTrue(result["yielded"])
        self.assertEqual(result["executed_count"], 0)

    def test_followup_drain_executes_pending_items_through_injected_executor(self) -> None:
        from tools.multi_position_sourcing.position_followups import (
            enqueue_position_followups,
            load_followup_queue,
        )
        from tools.multi_position_sourcing.position_intake_runner import drain_position_followups

        with tempfile.TemporaryDirectory() as tmp:
            queue_path = Path(tmp) / "followups.json"
            enqueue_position_followups(
                RegistrationOutcome(
                    status="created",
                    is_new_task=True,
                    reason="created",
                    task_id="86drain",
                    task_url="https://app.clickup.com/t/86drain",
                    dry_run=False,
                ),
                queue_path=queue_path,
                now_iso="2026-07-05T00:00:00Z",
            )
            calls: list[str] = []

            result = drain_position_followups(
                queue_path=queue_path,
                execute_followup=lambda item: calls.append(item["task"]) or {"ok": True},
                now_iso="2026-07-05T00:02:00Z",
            )
            queue = load_followup_queue(queue_path)

        self.assertEqual(calls, ["url_presetting", "jd_set_build"])
        self.assertEqual(result["executed_count"], 2)
        self.assertEqual({item["status"] for item in queue}, {"done"})

    def test_followup_drain_stops_after_executor_block(self) -> None:
        from tools.multi_position_sourcing.position_followups import (
            enqueue_position_followups,
            load_followup_queue,
        )
        from tools.multi_position_sourcing.position_intake_runner import drain_position_followups

        with tempfile.TemporaryDirectory() as tmp:
            queue_path = Path(tmp) / "followups.json"
            enqueue_position_followups(
                RegistrationOutcome(
                    status="created",
                    is_new_task=True,
                    reason="created",
                    task_id="86blocked",
                    task_url="https://app.clickup.com/t/86blocked",
                    dry_run=False,
                ),
                queue_path=queue_path,
            )
            calls: list[str] = []

            def blocked_executor(item):
                calls.append(item["task"])
                raise RuntimeError("captcha blocked")

            result = drain_position_followups(
                queue_path=queue_path,
                execute_followup=blocked_executor,
                now_iso="2026-07-05T00:03:00Z",
            )
            queue = load_followup_queue(queue_path)

        self.assertEqual(calls, ["url_presetting"])
        self.assertEqual(result["executed_count"], 0)
        self.assertEqual([item["status"] for item in queue], ["blocked", "pending"])

    def test_intake_state_suppresses_repeated_pending_and_processed_mail(self) -> None:
        from tools.multi_position_sourcing.position_followups import load_followup_queue
        from tools.multi_position_sourcing.position_intake_runner import (
            IntakeEmail,
            run_position_intake_tick,
        )
        from tools.multi_position_sourcing.position_intake_state import load_intake_state

        register_calls: list[bool] = []

        def register_position(_parse_result, **kwargs):
            register_calls.append(kwargs["dry_run"])
            return RegistrationOutcome(
                status="created",
                is_new_task=True,
                reason="created",
                task_id="86state",
                task_url="https://app.clickup.com/t/86state",
                dry_run=kwargs["dry_run"],
            )

        email = IntakeEmail(message_id="msg-state", subject="JD 공유", body=LONG_JD_BODY)
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "state.json"
            queue_path = Path(tmp) / "followups.json"

            first = run_position_intake_tick(
                emails=(email,),
                register_position=register_position,
                queue_path=queue_path,
                state_path=state_path,
            )
            second = run_position_intake_tick(
                emails=(email,),
                register_position=register_position,
                queue_path=queue_path,
                state_path=state_path,
            )
            approved = run_position_intake_tick(
                emails=(email,),
                register_position=register_position,
                queue_path=queue_path,
                state_path=state_path,
                approved_message_ids=("msg-state",),
                now_iso="2026-07-05T00:04:00Z",
            )
            fourth = run_position_intake_tick(
                emails=(email,),
                register_position=register_position,
                queue_path=queue_path,
                state_path=state_path,
                approved_message_ids=("msg-state",),
            )
            state = load_intake_state(state_path)
            queue = load_followup_queue(queue_path)

        self.assertEqual(register_calls, [True, False])
        self.assertEqual(first["events"][0]["status"], "approval_required")
        self.assertEqual(second["events"][0]["status"], "approval_pending")
        self.assertEqual(approved["events"][0]["status"], "registered")
        self.assertEqual(fourth["events"][0]["status"], "already_processed")
        self.assertEqual(state["processed_message_ids"], ["msg-state"])
        self.assertEqual(state["pending_approval_message_ids"], [])
        self.assertEqual(len(queue), 2)

    def test_followup_drain_builds_url_and_jd_builder_commands_without_send(self) -> None:
        from tools.multi_position_sourcing.position_followups import enqueue_position_followups
        from tools.multi_position_sourcing.position_intake_runner import drain_position_followups

        with tempfile.TemporaryDirectory() as tmp:
            queue_path = Path(tmp) / "followups.json"
            enqueue_position_followups(
                RegistrationOutcome(
                    status="created",
                    is_new_task=True,
                    reason="created",
                    task_id="86commands",
                    task_url="https://app.clickup.com/t/86commands",
                    dry_run=False,
                ),
                queue_path=queue_path,
            )
            requests: list[dict[str, object]] = []

            result = drain_position_followups(
                queue_path=queue_path,
                execute_followup=lambda request: requests.append(request) or {"ok": True},
            )

        self.assertEqual(result["executed_count"], 2)
        self.assertEqual([request["prompt"] for request in requests], [
            "/url https://app.clickup.com/t/86commands",
            "jd builder https://app.clickup.com/t/86commands",
        ])
        self.assertEqual({request["send_allowed"] for request in requests}, {False})
        self.assertNotIn("send_clicked", json.dumps(requests, ensure_ascii=False).lower())
        self.assertNotIn("outreach", json.dumps(requests, ensure_ascii=False).lower())

    def test_routine_one_turn_searches_registers_then_drains_followups(self) -> None:
        from tools.multi_position_sourcing.position_intake_runner import (
            GMAIL_POSITION_INTAKE_QUERY,
            IntakeEmail,
            run_position_intake_routine_once,
        )

        seen_queries: list[str] = []
        register_calls: list[bool] = []

        def search_threads(query: str):
            seen_queries.append(query)
            return (IntakeEmail(message_id="msg-routine", subject="JD 공유", body=LONG_JD_BODY),)

        def register_position(_parse_result, **kwargs):
            register_calls.append(kwargs["dry_run"])
            return RegistrationOutcome(
                status="created",
                is_new_task=True,
                reason="created",
                task_id="86routine",
                task_url="https://app.clickup.com/t/86routine",
                dry_run=kwargs["dry_run"],
            )

        with tempfile.TemporaryDirectory() as tmp:
            result = run_position_intake_routine_once(
                search_threads=search_threads,
                register_position=register_position,
                execute_followup=lambda request: {"ok": True, "prompt": request["prompt"]},
                queue_path=Path(tmp) / "followups.json",
                state_path=Path(tmp) / "state.json",
                approved_message_ids=("msg-routine",),
                now_iso="2026-07-05T00:05:00Z",
            )

        self.assertEqual(seen_queries, [GMAIL_POSITION_INTAKE_QUERY])
        self.assertEqual(register_calls, [False])
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["intake"]["enqueued_count"], 2)
        self.assertEqual(result["drain"]["executed_count"], 2)
        self.assertEqual(result["followup_prompts"], [
            "/url https://app.clickup.com/t/86routine",
            "jd builder https://app.clickup.com/t/86routine",
        ])

    def test_routine_owner_activity_yields_before_gmail_or_followup_adapters(self) -> None:
        from tools.multi_position_sourcing.position_intake_runner import (
            run_position_intake_routine_once,
        )

        search_calls: list[str] = []
        followup_calls: list[dict[str, object]] = []

        result = run_position_intake_routine_once(
            search_threads=lambda query: search_calls.append(query) or (),
            execute_followup=lambda request: followup_calls.append(request),
            owner_activity_detected=True,
        )

        self.assertEqual(result["status"], "yielded")
        self.assertEqual(search_calls, [])
        self.assertEqual(followup_calls, [])

    def test_position_intake_cli_fake_json_smoke_exit_zero(self) -> None:
        from tools.multi_position_sourcing.position_intake_runner import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            emails_path = root / "emails.json"
            output_path = root / "out.json"
            emails_path.write_text(
                json.dumps(
                    {
                        "emails": [
                            {
                                "message_id": "msg-cli",
                                "subject": "JD 공유",
                                "body": LONG_JD_BODY,
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            rc = main(
                [
                    "--executor", "fake",
                    "--emails-json", str(emails_path),
                    "--queue-path", str(root / "followups.json"),
                    "--state-path", str(root / "state.json"),
                    "--approved-message-id", "msg-cli",
                    "--output", str(output_path),
                    "--skip-owner-check",
                ]
            )
            payload = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(rc, 0)
        self.assertEqual(payload["executor"], "fake")
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["intake"]["email_count"], 1)
        self.assertEqual(payload["drain"]["executed_count"], 2)
        self.assertEqual(payload["followup_prompts"], [
            "/url https://app.clickup.com/t/86fakeintake",
            "jd builder https://app.clickup.com/t/86fakeintake",
        ])
        self.assertNotIn("send_clicked", json.dumps(payload, ensure_ascii=False).lower())

    def test_position_intake_cli_live_mode_is_explicitly_blocked_locally(self) -> None:
        from tools.multi_position_sourcing.position_intake_runner import main

        rc = main(["--executor", "live", "--emails-json", "unused.json"])

        self.assertEqual(rc, 2)

    def test_dry_run_payload_wires_position_intake_pipeline_demo(self) -> None:
        from tools.multi_position_sourcing.dry_run import build_dry_run_payload

        payload = build_dry_run_payload()
        demo = payload["sample_position_intake_pipeline"]

        self.assertEqual(demo["routine_status"], "ok")
        self.assertEqual(demo["queued_tasks"], ["url_presetting", "jd_set_build"])
        self.assertEqual(demo["followup_prompts"], [
            "/url https://app.clickup.com/t/86sampleintake",
            "jd builder https://app.clickup.com/t/86sampleintake",
        ])
        self.assertEqual(demo["drain"]["executed_count"], 2)
        self.assertEqual(demo["send_tasks"], [])
        self.assertEqual(demo["result"]["enqueued_count"], 2)
        self.assertEqual(demo["register_calls"][0]["dry_run"], False)


if __name__ == "__main__":
    unittest.main()
