"""V1 독립 적대검증 3라운드(2026-07-31) — 재검증 FAIL 판정 대응.

goal: docs/engineering/aisearch-review-fix-goal-2026-07-31.md `## 적대 검증 로그`

V1 재검증이 실제 공격으로 재현한 것:
① 증거가 **실물**이 아니어도 통과 — 없는 manifest 경로 + 아무 64자리 해시.
② 제외어가 점수자료 전체를 훑어 **채용공고 요구문구**("인턴 경험 제외")에 오탐.
⑥ 사람 개입으로 멈춘 뒤에도 정리 구문(배너 해제)이 브라우저 명령을 실행.
⑦ 저장 잠금이 10초를 넘기면 **살아 있는** 저장자의 잠금까지 지운다.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path

import pytest

from apps.aisearch.core.recorders import Candidate, DualRecorder, has_saved_profile_evidence
from apps.aisearch.core.orchestrator import _find_exclusion_match
from apps.aisearch.core.pagination_store import TABLE_NAME, make_row_id
from apps.aisearch.run import JsonlPageStore

POSITION = "Tech PM"
URL = "https://www.linkedin.com/in/hong/"
CHANNEL = "linkedin_rps"


def _make_real_evidence(tmp_path: Path) -> dict:
    """실제로 존재하는 manifest + 실제 스크린샷 해시로 만든 영수증."""
    shot = tmp_path / "profile.png"
    shot.write_bytes(b"fake-screenshot-bytes")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"profile_url": URL}), encoding="utf-8")
    return {
        "profile_url": URL,
        "site": CHANNEL,
        "position_id": POSITION,
        "task": "aisearch",
        "mode": "profile",
        "manifest_path": str(manifest),
        "screenshot_path": str(shot),
        "screenshot_sha256": hashlib.sha256(shot.read_bytes()).hexdigest(),
    }


# ── ① 증거는 디스크에 실재해야 한다 ────────────────────────────────────────


def test_v1r3_evidence_with_nonexistent_manifest_is_rejected(tmp_path):
    ev = _make_real_evidence(tmp_path)
    ev["manifest_path"] = str(tmp_path / "없는파일.json")
    assert not has_saved_profile_evidence(
        ev, profile_url=URL, channel=CHANNEL, position_id=POSITION
    ), "존재하지 않는 manifest 경로가 증거로 인정됐다"


def test_v1r3_evidence_with_wrong_screenshot_hash_is_rejected(tmp_path):
    ev = _make_real_evidence(tmp_path)
    ev["screenshot_sha256"] = "0" * 64
    assert not has_saved_profile_evidence(
        ev, profile_url=URL, channel=CHANNEL, position_id=POSITION
    ), "스크린샷 해시가 실제 파일과 달라도 통과했다"


def test_v1r3_evidence_without_screenshot_path_is_rejected(tmp_path):
    ev = _make_real_evidence(tmp_path)
    ev.pop("screenshot_path")
    assert not has_saved_profile_evidence(
        ev, profile_url=URL, channel=CHANNEL, position_id=POSITION
    ), "해시만 있고 실물 파일을 가리키지 않는 증거가 통과했다"


def test_v1r3_site_is_required(tmp_path):
    ev = _make_real_evidence(tmp_path)
    ev.pop("site")
    assert not has_saved_profile_evidence(
        ev, profile_url=URL, channel=CHANNEL, position_id=POSITION
    ), "site 를 생략해 채널 대조를 건너뛸 수 있었다"


def test_v1r3_real_evidence_passes(tmp_path):
    ev = _make_real_evidence(tmp_path)
    assert has_saved_profile_evidence(
        ev, profile_url=URL, channel=CHANNEL, position_id=POSITION
    )


def test_v1r3_fabricated_evidence_does_not_register(tmp_path):
    class _CU:
        def __init__(self):
            self.created_subtasks = []
            self.created_tasks = []

        def find_parent_task(self, *a):
            return None

        def subtask_exists_with_profile_url(self, *a):
            return False

        def create_parent_task(self, *a):
            self.created_tasks.append(a)
            return "p"

        def create_candidate_subtask(self, l, p, f):
            self.created_subtasks.append(f)
            return "s"

    class _DC:
        def post_message(self, c, m):
            return "m"

    class _AD:
        def __init__(self):
            self.registered = []

        def register_candidate(self, payload):
            self.registered.append(payload)
            return {"ok": True, "candidate": {"id": "x"}, "deduped": False}

    cu, ad = _CU(), _AD()
    rec = DualRecorder(clickup=cu, discord=_DC(), admin=ad, live=True, owner_signoff=True)
    ev = _make_real_evidence(tmp_path)
    ev["manifest_path"] = "/없는/경로/manifest.json"

    result = rec.record(
        position_name=POSITION,
        candidate=Candidate(
            profile_url=URL, score=87, why_fit="적합", profile_summary="요약", evidence=ev
        ),
        channel=CHANNEL,
    )

    assert result.status == "failed"
    assert cu.created_subtasks == []
    assert ad.registered == []


# ── ② 채용공고 요구문구가 후보를 떨구면 안 된다 ────────────────────────────


def _cand_with_requirement(requirement: str = "인턴 경험 제외"):
    return {
        "score_payload": {
            "score": 88,
            # JD 에서 복사된 평가 기준 문구 — 후보 정보가 아니다.
            "requirement": requirement,
            "criteria": [requirement],
            "dimensions": {"D3": {"evidence": "기구설계 10년 수행"}},
        },
        "record": {"profile_url": URL, "why_fit": "적합", "profile_summary": "요약"},
        "draft_inputs": {"candidate_headline": "기구설계 파트리더"},
    }


def test_v1r3_jd_requirement_text_in_score_payload_does_not_exclude():
    assert _find_exclusion_match(_cand_with_requirement(), ["인턴"]) is None, (
        "채용공고 요구문구('인턴 경험 제외')가 정상 후보를 떨궜다"
    )


def test_v1r3_candidate_evidence_in_score_payload_still_scanned():
    cand = _cand_with_requirement()
    cand["score_payload"]["dimensions"]["D3"]["evidence"] = "인턴 6개월 수행"
    matched = _find_exclusion_match(cand, ["인턴"])
    assert matched is not None, "점수 근거(evidence)의 제외어를 놓쳤다"
    assert "evidence" in matched[1]


# ── ⑥ 개입으로 멈춘 뒤에는 브라우저 명령을 더 보내지 않는다 ────────────────


def test_v1r3_no_browser_command_after_human_intervention():
    from apps.aisearch.core.orchestrator import run_search_pipeline
    from tests.test_aisearch_orchestrator import Harness, _jd

    h = Harness(pages=3)
    intervened = threading.Event()
    after: list[str] = []
    real_driver = h.driver

    class _WatchedDriver:
        """개입 이후에 브라우저로 나간 명령을 센다."""

        def run_js(self, snippet: str) -> None:
            if intervened.is_set():
                after.append(snippet)
            real_driver.run_js(snippet)

    watched = _WatchedDriver()
    h.driver = watched

    def side_effect(channel: str, page: int) -> None:
        if page == 1 and not intervened.is_set():
            h.monitor.on_human_input()  # 사장님이 크롬을 만졌다
            intervened.set()

    h.list_side_effect = side_effect
    report = run_search_pipeline(_jd(), h.deps())

    assert report.status == "waiting_resume"
    # 개입 감지 이후에는 배너 해제 같은 추가 JS 도 보내지 않는다(SOT 불변식 2).
    assert after == [], f"개입 후에도 브라우저 명령이 {len(after)}회 나갔다: {after}"
    # 대신 왜 배너를 안 지웠는지는 리포트에 남는다(조용한 생략 금지).
    assert any("배너 해제 보류" in e["error"] for e in report.banner_errors)


# ── ⑦ 저장 잠금은 살아 있는 저장자의 것을 뺏지 않는다 ──────────────────────


def _row(url: str) -> dict:
    return {
        "id": make_row_id(channel="saramin", page_type="list", url=url, position_ref="P1"),
        "channel": "saramin",
        "page_type": "list",
        "url": url,
        "position_ref": "P1",
        "raw_html_or_text": "<html/>",
        "machine": "m",
        "captured_at": "2026-07-31T00:00:00+00:00",
    }


def test_v1r3_slow_writer_lock_is_not_stolen(tmp_path):
    """느린 저장자(오래 걸리는 쓰기)의 잠금을 다른 저장자가 뺏으면 안 된다."""
    path = tmp_path / "pages.jsonl"
    a = JsonlPageStore(path)
    b = JsonlPageStore(path)

    started = threading.Event()
    release = threading.Event()
    errors: list[BaseException] = []

    original = a._write_payload if hasattr(a, "_write_payload") else None

    def slow_upsert():
        try:
            with a._file_lock():  # 잠금을 오래 붙잡는다
                started.set()
                release.wait(timeout=5)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    worker = threading.Thread(target=slow_upsert)
    worker.start()
    assert started.wait(timeout=5)

    # B 는 A 가 놓을 때까지 기다려야 하며, 훔쳐서는 안 된다.
    def b_writes():
        try:
            b.upsert(TABLE_NAME, _row("https://p/2"))
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    b_thread = threading.Thread(target=b_writes)
    b_thread.start()
    time.sleep(0.2)
    assert b_thread.is_alive(), "A 가 잠금을 쥐고 있는데 B 가 먼저 써버렸다"

    release.set()
    worker.join(timeout=5)
    b_thread.join(timeout=5)
    assert errors == [], f"잠금 처리 중 오류: {errors}"

    a.upsert(TABLE_NAME, _row("https://p/1"))
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert {r["url"] for r in rows} == {"https://p/1", "https://p/2"}
