"""AC-3 — 안전 게이트 1층(봇/워커 코드) 기계 검증 (goal: discord-single-bot-console §7 G4).

G4 로그인 선행 게이트: 검색 스킬 잡은 로그인 영수증(artifacts/portal_session_status_latest.json)
이 유효할 때만 시작한다. 아니면 잡을 paused_for_human 으로 세우고 사장님을 호출한다.
훅(H2)은 2층일 뿐 — 1층은 워커 코드 안의 이 게이트다(훅 fail-open 전제).

- 순수 판정 함수 login_gate_block_reason(payload, job, now_epoch):
  영수증 없음/깨짐/만료(86400s, fleet_heartbeat 과 동일 기준)/필요 채널 not-ready → 사유 문자열.
  전 채널 ready + 신선 → None.
- run_once 배선: 기본 러너(비주입) 검색 잡은 게이트 통과 전 러너 실행 0회,
  paused_for_human 으로 release + 알림. 주입 러너(테스트/시뮬레이션)는 기존 행동 유지.
"""

from __future__ import annotations

import json
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from tools.multi_position_sourcing.fleet_worker import (
    FleetWorker,
    _run_login_preflight,
    login_gate_block_reason,
)

NOW = int(time.time())


def _receipt(*, ready=True, channels=("saramin", "jobkorea", "linkedin_rps"),
             age_seconds=60, per_channel=None):
    from datetime import datetime, timezone
    gen = datetime.fromtimestamp(NOW - age_seconds, tz=timezone.utc).isoformat()
    sessions = []
    for ch in channels:
        r = ready if per_channel is None else per_channel.get(ch, ready)
        sessions.append({"channel": ch, "ready": r, "login": "ok" if r else "expired"})
    return {
        "kind": "portal_session_preflight",
        "generated_at": gen,
        "ready": all(s["ready"] for s in sessions),
        "portal_sessions": sessions,
    }


def _job(**over):
    j = {
        "id": 7, "machine": "macmini", "skill": "humansearch",
        "position_url": "https://app.clickup.com/t/86ey4umzk",
        "requested_by": "814353841088757800:owner", "role": "owner",
        "params": {}, "account_key": "portal:macmini",
    }
    j.update(over)
    return j


class LoginGateReasonTests(unittest.TestCase):
    def test_missing_payload_blocks(self) -> None:
        self.assertIsNotNone(login_gate_block_reason(None, _job(), NOW))
        self.assertIsNotNone(login_gate_block_reason("garbage", _job(), NOW))
        self.assertIsNotNone(login_gate_block_reason({}, _job(), NOW))

    def test_fresh_ready_receipt_passes(self) -> None:
        self.assertIsNone(login_gate_block_reason(_receipt(), _job(), NOW))

    def test_stale_receipt_blocks(self) -> None:
        payload = _receipt(age_seconds=86400 + 60)
        self.assertIsNotNone(login_gate_block_reason(payload, _job(), NOW))

    def test_channel_not_ready_blocks_only_when_required(self) -> None:
        payload = _receipt(per_channel={"saramin": True, "jobkorea": False,
                                        "linkedin_rps": True})
        # humansearch 기본 채널(saramin+jobkorea) — jobkorea not ready → 차단
        self.assertIsNotNone(login_gate_block_reason(payload, _job(), NOW))
        # saramin 만 요구하는 잡 → 통과
        job = _job(params={"channels": ["saramin"]})
        self.assertIsNone(login_gate_block_reason(payload, job, NOW))

    def test_url_skill_requires_linkedin(self) -> None:
        payload = _receipt(per_channel={"saramin": True, "jobkorea": True,
                                        "linkedin_rps": False})
        self.assertIsNotNone(login_gate_block_reason(payload, _job(skill="url"), NOW))

    def test_public_web_only_search_needs_no_portal_login(self) -> None:
        job = _job(skill="aisearch", params={"channels": ["public_web"]})
        self.assertIsNone(login_gate_block_reason(None, job, NOW))

    def test_missing_required_channel_entry_blocks(self) -> None:
        payload = _receipt(channels=("saramin",))  # jobkorea 항목 자체가 없음
        self.assertIsNotNone(login_gate_block_reason(payload, _job(), NOW))

    def test_naive_or_future_generated_at_blocks(self) -> None:
        payload = _receipt()
        payload["generated_at"] = "2026-07-22T00:00:00"  # tz 없음 → 신뢰 불가
        self.assertIsNotNone(login_gate_block_reason(payload, _job(), NOW))


class LoginPreflightRunnerTests(unittest.TestCase):
    def test_url_preflight_uses_only_linkedin_and_never_waits_for_human(self) -> None:
        completed = SimpleNamespace(returncode=0, stdout="", stderr="")
        with patch(
            "tools.multi_position_sourcing.fleet_worker.subprocess.run",
            return_value=completed,
        ) as runner:
            self.assertTrue(_run_login_preflight(_job(skill="url")))
        command = runner.call_args.args[0]
        self.assertEqual(command[command.index("--channels") + 1], "linkedin_rps")
        self.assertIn("--no-human-intervention", command)

    def test_preflight_failure_is_fail_closed(self) -> None:
        completed = SimpleNamespace(returncode=1, stdout="", stderr="secret upstream detail")
        with patch(
            "tools.multi_position_sourcing.fleet_worker.subprocess.run",
            return_value=completed,
        ):
            self.assertFalse(_run_login_preflight(_job()))


class WorkerFakeQueue:
    def __init__(self, job):
        self._job = job
        self.released = []
        self.enqueued = []

    def enqueue(self, payload):
        self.enqueued.append(payload)
        return {"id": 99, **payload}

    def claim_next(self, machine):
        j, self._job = self._job, None
        return j

    def release(self, job_id, status, *, result_summary="", error=""):
        self.released.append((job_id, status, result_summary, error))
        return [{"id": job_id, "status": status}]


class LoginGateWiringTests(unittest.TestCase):
    def setUp(self) -> None:
        from tools.multi_position_sourcing import fleet_worker
        patcher = patch.object(fleet_worker, "discord_notify", lambda job, text: None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _run(self, tmp_receipt, job, *, receipt_after_preflight=None,
             preflight_ok=False):
        from tools.multi_position_sourcing import fleet_worker as fw
        calls = []
        preflights = []
        receipt_reads = iter((tmp_receipt, receipt_after_preflight))

        def fake_run(cmd, **kwargs):
            calls.append(list(cmd))
            return SimpleNamespace(stdout="ok", stderr="", returncode=0)

        notes = []
        with patch.object(fw.subprocess, "run", fake_run), \
             patch.object(
                 fw, "_read_login_receipt",
                 lambda: next(receipt_reads, receipt_after_preflight)), \
             patch.object(
                 fw, "_run_login_preflight",
                 lambda current_job: preflights.append(current_job) or preflight_ok):
            q = WorkerFakeQueue(job)
            w = FleetWorker(machine="macmini", queue=q,
                            notifier=lambda j, t: notes.append(t))
            status = w.run_once()
        return status, q, calls, notes, preflights

    def test_search_job_without_receipt_runs_login_first_then_pauses(self) -> None:
        status, q, calls, notes, preflights = self._run(None, _job())
        self.assertEqual(status, "paused_for_human")
        self.assertEqual(calls, [], "러너(subprocess)가 실행되면 안 됨")
        self.assertEqual(len(preflights), 1)
        self.assertEqual(q.released[-1][1], "paused_for_human")
        self.assertTrue(any("로그인" in n for n in notes), notes)

    def test_auto_login_success_continues_same_search_job(self) -> None:
        status, q, calls, notes, preflights = self._run(
            None,
            _job(params={"agent": "claude"}),
            receipt_after_preflight=_receipt(),
            preflight_ok=True,
        )
        self.assertGreaterEqual(len(preflights), 1)
        self.assertGreaterEqual(len(calls), 1, "로그인 뒤 검색 러너가 이어서 실행돼야 함")
        self.assertNotEqual(status, "paused_for_human")
        self.assertTrue(any("로그인" in n for n in notes), notes)

    def test_search_job_with_fresh_receipt_runs(self) -> None:
        status, q, calls, _notes, preflights = self._run(
            _receipt(), _job(params={"agent": "claude"}))
        # 러너는 실행됐다(영수증 통과). 결과 상태는 출력 계약에 따름 — 여기선 실행 여부만.
        self.assertGreaterEqual(len(calls), 1)
        self.assertEqual(preflights, [])

    def test_injected_runner_keeps_legacy_behavior(self) -> None:
        # 주입 러너(테스트 하위호환) — 게이트 미적용으로 기존 스위트가 계속 성립.
        q = WorkerFakeQueue(_job())
        done = 'ok\nHUMANSEARCH_EVIDENCE_RECEIPT:{"opened_profiles":0,"profile_evidence":[]}'
        w = FleetWorker(machine="macmini", queue=q, runner=lambda p, t: (done, 0),
                        notifier=lambda j, t: None)
        self.assertEqual(w.run_once(), "done")


if __name__ == "__main__":
    unittest.main()
