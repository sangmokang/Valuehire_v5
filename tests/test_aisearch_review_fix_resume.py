"""2026-07-31 전수 리뷰 — H3/F6 자동 재개 · F7 재개 후 집계 (U5/U16).

goal: docs/engineering/aisearch-review-fix-goal-2026-07-31.md
SOT 불변식 2(CLAUDE.md): "멈추고 방치하지 않는다 — 반드시 자동으로 재개하며,
자동 재개를 영구 차단하는 코드(작업 목록 폐기·무기한 중단)는 SOT 위반."

- F6: 재개 시도를 6회(=30초)로 고정 소진하고 waiting_resume 로 끝내는 경로가
  남아 있으면 SOT 위반이다. 기본값은 **상한 없음**이어야 한다.
- F7: 재개 실행에서 이미 완결된 후보를 건너뛰면서 리포트 registered/drafts 에
  넣지 않아, 재개가 한 번이라도 돌면 수치가 줄고 초안이 영구 누락됐다.
"""
from __future__ import annotations

import pytest

import inspect
import json

from apps.aisearch import run as run_mod
from apps.aisearch.core.discord_notify import DiscordNotifier
from apps.aisearch.core.intervention import RESUME_DELAY_SECONDS
from tests.test_aisearch_resume_loop import (
    JD,
    _OneShotHumanInputTransport,
    _write_jd,
)


# ── F6 — 기본은 무제한 재개(멈추고 방치 금지) ──────────────────────────────


@pytest.fixture(autouse=True)
def _structural_evidence_verifier(monkeypatch):
    """영수증 **실물** 무결성은 전용 테스트가 지킨다 — 여기서는 모양 검사로 대체.

    프로덕션 기본값이 정본 검증기(browser_evidence.complete_evidence_payload)라는
    사실은 tests/test_aisearch_v1_round3.py 가 따로 잠근다.
    """
    from tests.aisearch_evidence import use_structural_verifier

    use_structural_verifier(monkeypatch)


def test_f6_default_has_no_resume_attempt_cap():
    default = inspect.signature(run_mod.main).parameters["max_resume_attempts"].default
    assert default is None, (
        "재개 시도 상한이 기본값으로 남아 있다 — 상한을 소진하면 '멈추고 방치'가 "
        "된다(SOT 불변식 2 위반)"
    )


def test_f6_resumes_even_when_owner_uses_chrome_longer_than_30_seconds(
    tmp_path, monkeypatch
):
    """사장님이 30초 넘게(=예전 상한 6회 초과) 크롬을 써도 결국 자동 재개한다."""
    fake_now = [0.0]
    monkeypatch.setattr(run_mod.time, "monotonic", lambda: fake_now[0])

    class _LongHumanInputTransport(_OneShotHumanInputTransport):
        """앞선 20회 스냅샷 동안 계속 사람 입력 — 그 뒤에야 손을 뗀다."""

        BUSY_SNAPSHOTS = 20

        def __call__(self, method: str, params: dict) -> dict:
            result = super().__call__(method, params)
            expr = params.get("expression", "")
            if "/*vh:snapshot*/" in expr:
                if self._snapshot_calls <= self.BUSY_SNAPSHOTS:
                    result["result"]["value"]["h"] = self._snapshot_calls
                else:
                    # 손을 뗐다. 실제 페이지 컨텍스트의 입력 카운터는 이동할
                    # 때마다 0에서 다시 시작하므로 0을 돌려준다(새 입력 없음).
                    result["result"]["value"]["h"] = 0
            return result

    slept: list[float] = []

    def fake_sleep(seconds: float) -> None:
        slept.append(seconds)
        fake_now[0] += seconds

    code = run_mod.main(
        [
            _write_jd(tmp_path),
            "--browser",
            "--ws-url",
            "ws://injected-not-used",
            "--pages-out",
            str(tmp_path / "pages.jsonl"),
        ],
        transport_factory=lambda ws_url: _LongHumanInputTransport(),
        extractors={ch: (lambda pages: []) for ch in run_mod.CHANNELS},
        notifier=DiscordNotifier(send=[].append, live=True),
        sleep=fake_sleep,
    )

    assert code == 0, "30초를 넘겨 개입해도 끝내 자동 재개해야 한다"
    assert len(slept) > 6, (
        f"예전 상한(6회)에서 포기했다 — 실제 대기 횟수 {len(slept)}"
    )
    assert all(s <= RESUME_DELAY_SECONDS for s in slept), "한 번에 너무 오래 자면 재개가 늦다"


def test_f6_explicit_cap_still_honoured_for_ops_and_tests(tmp_path, monkeypatch):
    """운영/테스트가 명시적으로 상한을 주면 그때만 멈춘다(기본값 아님)."""
    monkeypatch.setattr(run_mod.time, "monotonic", lambda: 0.0)

    class _AlwaysHumanInputTransport(_OneShotHumanInputTransport):
        def __call__(self, method: str, params: dict) -> dict:
            result = super().__call__(method, params)
            if "/*vh:snapshot*/" in params.get("expression", ""):
                result["result"]["value"]["h"] = self._snapshot_calls
            return result

    slept: list[float] = []
    code = run_mod.main(
        [
            _write_jd(tmp_path),
            "--browser",
            "--ws-url",
            "ws://injected-not-used",
            "--pages-out",
            str(tmp_path / "pages.jsonl"),
        ],
        transport_factory=lambda ws_url: _AlwaysHumanInputTransport(),
        extractors={ch: (lambda pages: []) for ch in run_mod.CHANNELS},
        notifier=DiscordNotifier(send=[].append, live=True),
        sleep=slept.append,
        max_resume_attempts=3,
    )

    assert code != 0
    assert len(slept) == 3


# ── F7 — 재개 후에도 리포트 수치·초안이 온전하다 ───────────────────────────


def test_f7_resume_keeps_completed_candidates_in_report_and_drafts():
    from apps.aisearch.core.orchestrator import run_search_pipeline
    from tests.test_aisearch_orchestrator import (
        PAYLOAD_60,
        Harness,
        _candidate,
        _jd,
    )

    h = Harness(pages=1)
    jd = _jd()
    cand = _candidate(PAYLOAD_60, "https://www.linkedin.com/talent/profile/aminexamplep60")
    for channel in ("linkedin_rps", "saramin", "jobkorea"):
        h.candidates[channel] = [dict(cand)]

    first = run_search_pipeline(jd, h.deps())
    assert first.registered, "1차 실행에서 등록이 있어야 비교가 성립한다"
    first_registered = len(first.registered)
    first_drafts = len(first.drafts)

    # 재개 실행 — 이미 완결된 후보는 재기록(중복 발신)하지 않지만,
    # 리포트 수치와 초안은 그대로 유지돼야 한다.
    resumed = run_search_pipeline(jd, h.deps(), previous=first)

    assert len(resumed.registered) == first_registered, (
        f"재개 후 등록 수가 줄었다: {first_registered} → {len(resumed.registered)}"
    )
    assert len(resumed.drafts) == first_drafts, (
        f"재개 후 초안이 누락됐다: {first_drafts} → {len(resumed.drafts)}"
    )


def test_f7_resume_does_not_write_externally_twice():
    """수치는 유지하되 외부 쓰기(ClickUp/Discord/admin)는 두 번 나가지 않는다."""
    from apps.aisearch.core.orchestrator import run_search_pipeline
    from tests.test_aisearch_orchestrator import (
        PAYLOAD_60,
        Harness,
        _candidate,
        _jd,
    )

    h = Harness(pages=1, live_recorder=True)
    jd = _jd()
    for channel in ("linkedin_rps", "saramin", "jobkorea"):
        h.candidates[channel] = [
            _candidate(PAYLOAD_60, f"https://www.linkedin.com/talent/profile/{channel}60")
        ]

    first = run_search_pipeline(jd, h.deps())
    admin_after_first = len(h.admin.registered)
    subtasks_after_first = h.clickup.writes.count("subtask")
    assert admin_after_first > 0

    run_search_pipeline(jd, h.deps(), previous=first)

    assert len(h.admin.registered) == admin_after_first, "재개가 admin 에 중복 등록했다"
    assert h.clickup.writes.count("subtask") == subtasks_after_first, (
        "재개가 ClickUp 에 중복 subtask 를 만들었다"
    )
