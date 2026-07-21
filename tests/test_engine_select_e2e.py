"""AC-2 — 엔진 선택(claude|codex) 종단 연결 (goal: discord-single-bot-console §11 AC-2).

봇(슬래시 인터랙션) → 큐 행(params.agent) → 워커 러너 선택까지 params.agent 가
끊기지 않고 전달됨을 한 테스트 파일에서 종단으로 봉인한다.

- engine:codex 인터랙션 → 큐 행 params.agent == "codex" → 그 행을 워커가 집으면
  codex exec 가 선택되고, 실패/타임아웃 라벨도 codex 로 기록된다.
- engine 미지정 → claude.
- E8(결정 ㉮): 그 머신에 codex 실행파일이 없으면(FileNotFoundError) 잡을 즉시
  failed 로 종결하고 알림을 남긴다 — 조용히 claude 로 대체하지 않는다.
"""

from __future__ import annotations

import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from scripts.discord_direct_gateway import handle_slash_interaction
from tests.test_discord_bot_console_ac1 import (
    AUTHORIZED,
    CLICKUP_URL,
    CONFIG,
    FakeQueue,
    _dm,
)
from tools.multi_position_sourcing.fleet_worker import FleetWorker


def _receipt_stdout() -> str:
    """aisearch 완료 영수증 계약(validate_aisearch_receipt)을 만족하는 최소 stdout.

    tests/test_fleet_worker.py 의 _receipt() 와 동일 형식 — 실행형 잡은 영수증 없이
    done 이 될 수 없다는 기존 계약을 그대로 존중한다(이 테스트의 관심사는 엔진 선택).
    """
    import json
    channel = {
        "login_verified": True, "query_verified": True,
        "result_count_verified": True, "pages_visited": 10,
        "last_page_reached": False, "opened_profiles": 0,
        "saved_receipts": 0, "candidates": [],
    }
    return "FLEET_SEARCH_RECEIPT:" + json.dumps(
        {"channels": {"saramin": channel, "jobkorea": dict(channel)}})


class WorkerFakeQueue:
    """FleetWorker 계약(tests/test_fleet_worker.py FakeQueue 와 동일 표면) — enqueue 행을 그대로 넘긴다."""

    def __init__(self, job: dict) -> None:
        self._job = dict(job)
        self._job.setdefault("id", 1)
        self.released: list[tuple] = []
        self.enqueued: list[dict] = []

    def enqueue(self, payload):
        self.enqueued.append(payload)
        return {"id": 99, **payload}

    def claim_next(self, machine: str):
        job, self._job = self._job, None
        return job

    def release(self, job_id, status, *, result_summary="", error=""):
        self.released.append((job_id, status, result_summary, error))
        return [{"id": job_id, "status": status}]


class EngineEndToEndTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        from tools.multi_position_sourcing import fleet_worker
        patcher = patch.object(fleet_worker, "discord_notify", lambda job, text: None)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def _enqueue(self, options: list[dict]) -> dict:
        queue = FakeQueue()
        result = await handle_slash_interaction(
            _dm("aisearch", options), queue=queue,
            authorized_users=AUTHORIZED, config=CONFIG)
        assert result["action"] == "enqueued", result
        return queue.enqueued[0]

    async def test_codex_flows_from_interaction_to_worker_runner(self) -> None:
        row = await self._enqueue([{"name": "url", "value": CLICKUP_URL},
                                   {"name": "engine", "value": "codex"}])
        self.assertEqual(row["params"]["agent"], "codex")

        from tools.multi_position_sourcing import fleet_worker as fw
        calls: list[list[str]] = []

        def fake_run(cmd, **kwargs):
            calls.append(list(cmd))
            return SimpleNamespace(stdout=_receipt_stdout(), stderr="", returncode=0)

        with patch.object(fw.subprocess, "run", fake_run):
            q = WorkerFakeQueue(row)
            worker = FleetWorker(machine=row["machine"], queue=q,
                                 notifier=lambda job, text: None)
            self.assertEqual(worker.run_once(), "done")
        self.assertEqual(calls[0][:2], ["codex", "exec"])

    async def test_unspecified_engine_flows_as_claude(self) -> None:
        row = await self._enqueue([{"name": "url", "value": CLICKUP_URL}])
        self.assertEqual(row["params"]["agent"], "claude")

        from tools.multi_position_sourcing import fleet_worker as fw
        calls: list[list[str]] = []

        def fake_run(cmd, **kwargs):
            calls.append(list(cmd))
            return SimpleNamespace(stdout=_receipt_stdout(), stderr="", returncode=0)

        with patch.object(fw.subprocess, "run", fake_run):
            q = WorkerFakeQueue(row)
            worker = FleetWorker(machine=row["machine"], queue=q,
                                 notifier=lambda job, text: None)
            self.assertEqual(worker.run_once(), "done")
        self.assertEqual(calls[0][:2], ["claude", "-p"])

    async def test_codex_missing_binary_fails_fast_with_codex_label(self) -> None:
        """E8 ㉮ — codex 없음 = 즉시 failed + 알림. claude 폴백 금지."""
        row = await self._enqueue([{"name": "url", "value": CLICKUP_URL},
                                   {"name": "engine", "value": "codex"}])

        from tools.multi_position_sourcing import fleet_worker as fw
        attempted: list[list[str]] = []

        def fake_run(cmd, **kwargs):
            attempted.append(list(cmd))
            raise FileNotFoundError("codex: command not found")

        notes: list[str] = []
        with patch.object(fw.subprocess, "run", fake_run):
            q = WorkerFakeQueue(row)
            worker = FleetWorker(machine=row["machine"], queue=q,
                                 notifier=lambda job, text: notes.append(text))
            self.assertEqual(worker.run_once(), "failed")
        # claude 로 재시도(폴백)하지 않았다 — 시도된 명령은 codex 1회뿐.
        self.assertEqual(len([c for c in attempted if c[:1] == ["claude"]]), 0)
        job_id, status, _summary, error = q.released[-1]
        self.assertEqual(status, "failed")
        self.assertTrue(any("실패" in n for n in notes), notes)

    async def test_codex_timeout_labeled_codex_not_claude(self) -> None:
        row = await self._enqueue([{"name": "url", "value": CLICKUP_URL},
                                   {"name": "engine", "value": "codex"}])
        from tools.multi_position_sourcing import fleet_worker as fw

        def fake_run(cmd, **kwargs):
            raise subprocess.TimeoutExpired(cmd=cmd, timeout=9)

        with patch.object(fw.subprocess, "run", fake_run):
            q = WorkerFakeQueue(row)
            worker = FleetWorker(machine=row["machine"], queue=q,
                                 notifier=lambda job, text: None)
            self.assertEqual(worker.run_once(), "failed")
        error = q.released[-1][3]
        self.assertIn("codex", error)
        self.assertNotIn("claude", error)


if __name__ == "__main__":
    unittest.main()
