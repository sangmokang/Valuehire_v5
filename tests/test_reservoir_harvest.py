"""저수지 모델 단계 2 — 연속 Harvest 라인 + 3머신 정책 + 관측 로그 계약.

인수 기준(기계 단언):
  2-1 관측 로그 계약: 모든 경계가 12필드 구조화 로그를 남기고, 필드 누락/잘못된 status는 raise.
  2-2 연속 Harvest 큐: 포지션 없이 segment_id만으로 돌고, 발견 프로필을 무조건 저장.
  2-3 3머신 멀티사이트 정책: 전담 사이트 없음·맥미니 우선·R4 양보·LinkedIn 시프트·단일 RPS 세션.
"""

from __future__ import annotations

import asyncio
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tools.multi_position_sourcing.reservoir_log import (
    RESERVOIR_LINES,
    RESERVOIR_LOG_FIELDS,
    RESERVOIR_STATUSES,
    ReservoirLogContractError,
    append_reservoir_log,
    make_reservoir_log_record,
    validate_reservoir_log_record,
)
from tools.multi_position_sourcing.harvest_policy import (
    HARVEST_MACHINES,
    HARVEST_SITES,
    linkedin_rps_operator,
    rps_session_conflict,
    sites_for_machine,
    startup_priority,
    worker_should_yield,
)
from tools.multi_position_sourcing.harvest_runner import (
    HarvestItem,
    arun_harvest_cycle,
    build_harvest_queue,
    run_harvest_cycle,
)


# ----------------------------------------------------------------------------
# 2-1 관측 로그 계약
# ----------------------------------------------------------------------------
class ReservoirLogContractTests(unittest.TestCase):
    REQUIRED = (
        "ts", "run_id", "machine", "segment_id", "site", "line",
        "in_count", "out_count", "dropped_count", "status", "fail_reason", "latency_ms",
    )

    def test_required_fields_are_exactly_the_twelve(self) -> None:
        self.assertEqual(set(RESERVOIR_LOG_FIELDS), set(self.REQUIRED))

    def test_lines_and_statuses_whitelist(self) -> None:
        self.assertEqual(set(RESERVOIR_LINES), {"harvest", "index", "match", "calibrate", "send"})
        self.assertEqual(set(RESERVOIR_STATUSES), {"ok", "fail", "skip"})

    def test_make_record_has_all_fields(self) -> None:
        rec = make_reservoir_log_record(
            ts="2026-06-12T00:00:00+00:00", run_id="r1", machine="macmini",
            segment_id="it_ai_data", site="saramin", line="harvest",
            in_count=10, out_count=10, dropped_count=0, status="ok",
        )
        for field in RESERVOIR_LOG_FIELDS:
            self.assertIn(field, rec)
        validate_reservoir_log_record(rec)  # must not raise

    def test_missing_field_is_rejected(self) -> None:
        rec = make_reservoir_log_record(
            ts="t", run_id="r", machine="m", segment_id="s", site="saramin",
            line="harvest", in_count=1, out_count=1, dropped_count=0, status="ok",
        )
        del rec["dropped_count"]
        with self.assertRaises(ReservoirLogContractError):
            validate_reservoir_log_record(rec)

    def test_bad_status_and_bad_line_rejected(self) -> None:
        base = dict(
            ts="t", run_id="r", machine="m", segment_id="s", site="saramin",
            line="harvest", in_count=1, out_count=1, dropped_count=0, status="ok",
            fail_reason="", latency_ms=0,
        )
        bad_status = dict(base, status="weird")
        with self.assertRaises(ReservoirLogContractError):
            validate_reservoir_log_record(bad_status)
        bad_line = dict(base, line="teleport")
        with self.assertRaises(ReservoirLogContractError):
            validate_reservoir_log_record(bad_line)

    def test_fail_closed_requires_reason(self) -> None:
        # status=fail 인데 fail_reason 비면 계약 위반(조용한 실패 금지).
        rec = make_reservoir_log_record(
            ts="t", run_id="r", machine="m", segment_id="s", site="jobkorea",
            line="harvest", in_count=5, out_count=0, dropped_count=5, status="fail",
            fail_reason="",
        )
        with self.assertRaises(ReservoirLogContractError):
            validate_reservoir_log_record(rec)

    def test_unknown_extra_field_rejected(self) -> None:
        # 스키마 자체가 계약 — 오타/잉여 필드는 로깅 버그를 가릴 수 있으므로 거부.
        rec = make_reservoir_log_record(
            ts="t", run_id="r", machine="m", segment_id="s", site="saramin",
            line="harvest", in_count=1, out_count=1, dropped_count=0, status="ok",
        )
        rec["linee"] = "typo"
        with self.assertRaises(ReservoirLogContractError):
            validate_reservoir_log_record(rec)

    def test_append_writes_dated_jsonl(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            rec = make_reservoir_log_record(
                ts="t", run_id="r", machine="macmini", segment_id="it_ai_data",
                site="saramin", line="harvest", in_count=3, out_count=3,
                dropped_count=0, status="ok",
            )
            path = append_reservoir_log(rec, root=root, today="2026-06-12")
            self.assertEqual(path, root / "logs" / "reservoir" / "2026-06-12.jsonl")
            lines = path.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 1)
            self.assertEqual(json.loads(lines[0])["segment_id"], "it_ai_data")


# ----------------------------------------------------------------------------
# 2-3 3머신 멀티사이트 정책
# ----------------------------------------------------------------------------
class HarvestPolicyTests(unittest.TestCase):
    def test_three_machines_and_startup_priority_macmini_first(self) -> None:
        self.assertEqual(set(HARVEST_MACHINES), {"macmini", "macbook", "macair"})
        self.assertEqual(startup_priority()[0], "macmini")

    def test_no_dedicated_site_all_machines_do_both(self) -> None:
        for machine in HARVEST_MACHINES:
            self.assertEqual(set(sites_for_machine(machine)), {"saramin", "jobkorea"})
        self.assertEqual(set(HARVEST_SITES), {"saramin", "jobkorea"})

    def test_r4_owner_activity_yields_worker(self) -> None:
        self.assertTrue(worker_should_yield(owner_activity_detected=True))
        self.assertFalse(worker_should_yield(owner_activity_detected=False))

    def test_linkedin_shift_day_macbook_night_macmini(self) -> None:
        self.assertEqual(linkedin_rps_operator(owner_present=True), "macbook")
        self.assertEqual(linkedin_rps_operator(owner_present=False), "macmini")

    def test_single_rps_session_guard(self) -> None:
        self.assertFalse(rps_session_conflict(["macbook"]))
        self.assertFalse(rps_session_conflict(["macmini", "macmini"]))
        self.assertTrue(rps_session_conflict(["macbook", "macmini"]))


# ----------------------------------------------------------------------------
# 2-2 연속 Harvest 큐 (포지션 없이) + 무조건 저장
# ----------------------------------------------------------------------------
SEGMENTS = ("it_ai_data", "marketing_growth")


class HarvestQueueTests(unittest.TestCase):
    def test_queue_built_from_segments_without_positions(self) -> None:
        active = ("macmini", "macbook")
        queue = build_harvest_queue(SEGMENTS, machines=active)
        # (segment × site) 만큼: 2 세그먼트 × 2 사이트 = 4
        self.assertEqual(len(queue), len(SEGMENTS) * len(HARVEST_SITES))
        for item in queue:
            self.assertIsInstance(item, HarvestItem)
            self.assertIn(item.segment_id, SEGMENTS)
            self.assertIn(item.channel, HARVEST_SITES)
            self.assertIn(item.machine, active)
            # 포지션 트리거가 없어야 한다.
            self.assertFalse(hasattr(item, "position_id"))

    def test_queue_round_robins_across_active_machines_deterministically(self) -> None:
        active = ("macmini", "macbook")
        q1 = build_harvest_queue(SEGMENTS, machines=active)
        q2 = build_harvest_queue(SEGMENTS, machines=active)
        self.assertEqual([i.machine for i in q1], [i.machine for i in q2])  # 결정론
        # 부하 분산: 두 머신이 모두 일감을 받는다.
        self.assertEqual(set(i.machine for i in q1), set(active))

    def test_harvest_cycle_saves_every_found_profile_unconditionally(self) -> None:
        active = ("macmini",)
        queue = build_harvest_queue(("it_ai_data",), machines=active)
        found = {
            ("it_ai_data", "saramin"): ("p1", "p2", "p3"),
            ("it_ai_data", "jobkorea"): ("p4", "p5"),
        }

        async def execute_item(item: HarvestItem):
            return found[(item.segment_id, item.channel)]

        saved: list[str] = []

        def save_rail(profile: str) -> None:
            saved.append(profile)

        summary = run_harvest_cycle(
            queue,
            execute_item=execute_item,
            save_rail=save_rail,
            run_id="run-1",
            today="2026-06-12",
        )
        # 발견 즉시 전부 저장 — save_rail 호출 == 발견 수, 누락 0.
        self.assertEqual(len(saved), 5)
        self.assertEqual(summary.saved_profiles, 5)
        self.assertEqual(summary.dropped, 0)
        # 모든 경계에 관측 로그 1줄(harvest 라인), 계약 만족.
        self.assertTrue(summary.log_records)
        for rec in summary.log_records:
            validate_reservoir_log_record(rec)
            self.assertEqual(rec["line"], "harvest")
            self.assertEqual(rec["run_id"], "run-1")

    def test_harvest_cycle_skips_when_owner_activity_and_logs_it(self) -> None:
        queue = build_harvest_queue(("it_ai_data",), machines=("macbook",))

        async def execute_item(item):  # pragma: no cover - should not be called
            raise AssertionError("must not search while owner present (R4)")

        summary = run_harvest_cycle(
            queue,
            execute_item=execute_item,
            save_rail=lambda p: None,
            run_id="run-2",
            today="2026-06-12",
            owner_activity_detected=True,
        )
        self.assertEqual(summary.saved_profiles, 0)
        self.assertTrue(summary.log_records)
        self.assertTrue(all(r["status"] == "skip" for r in summary.log_records))

    def test_harvest_cycle_fail_closed_records_drop_and_reason(self) -> None:
        queue = build_harvest_queue(("it_ai_data",), machines=("macmini",))

        async def execute_item(item):
            raise RuntimeError("portal selector failed")

        summary = run_harvest_cycle(
            queue,
            execute_item=execute_item,
            save_rail=lambda p: None,
            run_id="run-3",
            today="2026-06-12",
        )
        self.assertEqual(summary.saved_profiles, 0)
        self.assertEqual(summary.searched, ())  # fail 은 searched 에 기록되면 안 된다(sync 도 동일)
        fail_recs = [r for r in summary.log_records if r["status"] == "fail"]
        self.assertTrue(fail_recs)
        for r in fail_recs:
            self.assertTrue(r["fail_reason"])  # 조용한 실패 금지
            validate_reservoir_log_record(r)

    def test_harvest_cycle_fail_closed_when_save_rail_raises(self) -> None:
        # 아카이버 저장(save_rail)이 터져도 예외가 새지 않고, 빠진 건수+이유를 fail 로그로 남긴다.
        queue = build_harvest_queue(("it_ai_data",), machines=("macmini",))

        async def execute_item(item):
            return ("p1", "p2", "p3")

        calls = {"n": 0}

        def save_rail(profile):
            calls["n"] += 1
            if calls["n"] == 2:  # 첫 아이템의 두 번째 저장에서 실패
                raise RuntimeError("archiver write failed")

        summary = run_harvest_cycle(
            queue,
            execute_item=execute_item,
            save_rail=save_rail,
            run_id="run-4",
            today="2026-06-12",
        )
        fail_recs = [r for r in summary.log_records if r["status"] == "fail"]
        self.assertTrue(fail_recs)
        # saramin(1번째 아이템)만 저장 실패 → fail. jobkorea(2번째)는 성공 → searched 에 그것만
        # (fail 항목이 searched 로 새는 회귀 방지, sync 판 — V2 적대검증 지적 봉인).
        self.assertEqual(summary.searched, (("it_ai_data", "jobkorea"),))
        for r in fail_recs:
            self.assertTrue(r["fail_reason"])
            self.assertGreater(r["dropped_count"], 0)  # 빠진 건수를 반드시 남긴다
            validate_reservoir_log_record(r)
        self.assertGreater(summary.dropped, 0)
        # 모든 경계에 로그 1줄(아이템 수만큼) — 저장 실패해도 로그 누락 없음.
        self.assertEqual(len(summary.log_records), len(queue))


# ----------------------------------------------------------------------------
# PC-D2b — arun_harvest_cycle 은 sync run_harvest_cycle 과 의미론이 드리프트하면 안 된다
# (로그/저장/fail-closed 공유 헬퍼 단일출처, SOT5). 같은 시나리오를 async 경로로 반복.
# ----------------------------------------------------------------------------
class AsyncHarvestCycleParityTests(unittest.TestCase):
    def test_arun_harvest_cycle_saves_every_found_profile_unconditionally(self) -> None:
        active = ("macmini",)
        queue = build_harvest_queue(("it_ai_data",), machines=active)
        found = {
            ("it_ai_data", "saramin"): ("p1", "p2", "p3"),
            ("it_ai_data", "jobkorea"): ("p4", "p5"),
        }

        async def execute_item(item: HarvestItem):
            return found[(item.segment_id, item.channel)]

        saved: list[str] = []

        async def run():
            return await arun_harvest_cycle(
                queue,
                execute_item=execute_item,
                save_rail=saved.append,
                run_id="arun-1",
                today="2026-07-04",
            )

        summary = asyncio.run(run())
        self.assertEqual(len(saved), 5)
        self.assertEqual(summary.saved_profiles, 5)
        self.assertEqual(summary.dropped, 0)
        # ok 인 항목만 searched 에 기록(fail 이 섞였을 때 오탐 방지 회귀).
        self.assertEqual(
            set(summary.searched), {("it_ai_data", "saramin"), ("it_ai_data", "jobkorea")}
        )
        for rec in summary.log_records:
            validate_reservoir_log_record(rec)
            self.assertEqual(rec["line"], "harvest")
            self.assertEqual(rec["run_id"], "arun-1")

    def test_arun_harvest_cycle_skips_when_owner_activity(self) -> None:
        queue = build_harvest_queue(("it_ai_data",), machines=("macbook",))

        async def execute_item(item):  # pragma: no cover
            raise AssertionError("must not search while owner present (R4)")

        async def run():
            return await arun_harvest_cycle(
                queue,
                execute_item=execute_item,
                save_rail=lambda p: None,
                run_id="arun-2",
                today="2026-07-04",
                owner_activity_detected=True,
            )

        summary = asyncio.run(run())
        self.assertEqual(summary.saved_profiles, 0)
        self.assertTrue(all(r["status"] == "skip" for r in summary.log_records))

    def test_arun_harvest_cycle_fail_closed_on_execute_item_exception(self) -> None:
        queue = build_harvest_queue(("it_ai_data",), machines=("macmini",))

        async def execute_item(item):
            raise RuntimeError("portal selector failed")

        async def run():
            return await arun_harvest_cycle(
                queue,
                execute_item=execute_item,
                save_rail=lambda p: None,
                run_id="arun-3",
                today="2026-07-04",
            )

        summary = asyncio.run(run())
        self.assertEqual(summary.saved_profiles, 0)
        self.assertEqual(summary.searched, ())  # fail 은 searched 에 기록되면 안 된다
        fail_recs = [r for r in summary.log_records if r["status"] == "fail"]
        self.assertTrue(fail_recs)
        for r in fail_recs:
            self.assertTrue(r["fail_reason"])
            validate_reservoir_log_record(r)

    def test_arun_harvest_cycle_fail_closed_when_save_rail_raises(self) -> None:
        queue = build_harvest_queue(("it_ai_data",), machines=("macmini",))

        async def execute_item(item):
            return ("p1", "p2", "p3")

        calls = {"n": 0}

        def save_rail(profile):
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("archiver write failed")

        async def run():
            return await arun_harvest_cycle(
                queue,
                execute_item=execute_item,
                save_rail=save_rail,
                run_id="arun-4",
                today="2026-07-04",
            )

        summary = asyncio.run(run())
        fail_recs = [r for r in summary.log_records if r["status"] == "fail"]
        self.assertTrue(fail_recs)
        # saramin(1번째 아이템)만 저장 실패 → fail. jobkorea(2번째)는 성공 → searched 에 그것만.
        self.assertEqual(summary.searched, (("it_ai_data", "jobkorea"),))
        for r in fail_recs:
            self.assertTrue(r["fail_reason"])
            self.assertGreater(r["dropped_count"], 0)
            validate_reservoir_log_record(r)
        self.assertGreater(summary.dropped, 0)
        self.assertEqual(len(summary.log_records), len(queue))

    def test_arun_harvest_cycle_awaits_async_executor_within_running_loop(self) -> None:
        """이게 sync run_harvest_cycle 과의 핵심 차이(BUG-HARVEST-ASYNC 우회)."""
        queue = build_harvest_queue(("it_ai_data",), machines=("macmini",))

        async def execute_item(item):
            return ("prof-a", "prof-b")

        saved: list[str] = []

        async def outer():
            return await arun_harvest_cycle(
                queue,
                execute_item=execute_item,
                save_rail=saved.append,
                run_id="arun-5",
                today="2026-07-04",
            )

        summary = asyncio.run(outer())
        # queue = ("it_ai_data" × 2 사이트[사람인·잡코리아]) → execute_item 2회 × 2건 = 4건.
        self.assertEqual(summary.saved_profiles, 4)
        self.assertEqual(saved, ["prof-a", "prof-b", "prof-a", "prof-b"])


if __name__ == "__main__":
    unittest.main()
