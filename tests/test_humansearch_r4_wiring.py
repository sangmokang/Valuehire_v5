from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from tools.multi_position_sourcing import humansearch_cdp_run as hcr
from tools.multi_position_sourcing.harvest_policy import worker_should_yield
from tools.multi_position_sourcing.humansearch_preflight import PreflightError
from tools.multi_position_sourcing.owner_activity import compute_yield_decision
from tools.multi_position_sourcing.portal_worker import ProfileLockError


@dataclass(frozen=True)
class Snapshot:
    owner_activity_detected: bool
    detection_status: str = "ok"
    idle_seconds: float = 120.0
    portal_site_active: bool = False


class FakeTab:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True

    def disconnect(self) -> None:
        self.closed = True

    def eval(self, _script: str):
        return hcr.SEARCH_URL_BASE

    def mark_busy(self, _label: str, *, expected_url: str) -> bool:
        return expected_url == hcr.SEARCH_URL_BASE


def _cards(count: int) -> list[dict]:
    return [
        {
            "url": f"https://www.linkedin.com/talent/profile/{idx:03d}",
            "name": f"candidate-{idx:03d}",
        }
        for idx in range(count)
    ]


def _row(card: dict, idx: int) -> dict:
    return {
        "idx": idx,
        "name": card["name"],
        "url": card["url"],
        "hard_exclude": None,
        "score": 70,
        "otw": False,
        "education": "",
        "evidence": {"status": "saved", "manifest_path": f"/fixture/{idx}.json"},
    }


@pytest.fixture(autouse=True)
def no_human_delay(monkeypatch) -> None:
    monkeypatch.setattr(hcr, "human_delay", lambda: None)


def test_worker_should_yield_matches_owner_detector_grid() -> None:
    for frontmost_is_chrome in (True, False):
        for idle in (None, 0.0, 59.9, 60.0, 300.0):
            detected = compute_yield_decision(
                frontmost_is_chrome=frontmost_is_chrome,
                os_idle_seconds=idle,
            )
            assert hcr.owner_snapshot_should_yield(Snapshot(detected)) is worker_should_yield(
                owner_activity_detected=detected
            )


def test_owner_activity_before_first_profile_opens_zero(monkeypatch, tmp_path: Path) -> None:
    opened: list[str] = []
    monkeypatch.setattr(hcr, "OUT_DIR", tmp_path)
    monkeypatch.setattr(hcr, "LOG", tmp_path / "run.log")
    monkeypatch.setattr(
        hcr,
        "process_profile",
        lambda _tab, card, _idx, **_kwargs: opened.append(card["url"]) or _row(card, 1),
    )

    with pytest.raises(ProfileLockError, match="owner activity"):
        hcr.process_cards_with_r4(
            FakeTab(),
            _cards(3),
            owner_snapshot=lambda: Snapshot(True),
            live_check=lambda _tab: {"ok": True},
        )
    assert opened == []
    assert not (tmp_path / "results.json").exists()


def test_owner_activity_after_one_profile_preserves_partial_results(monkeypatch, tmp_path: Path) -> None:
    opened: list[str] = []
    snapshots = iter([Snapshot(False), Snapshot(True), Snapshot(False)])
    monkeypatch.setattr(hcr, "OUT_DIR", tmp_path)
    monkeypatch.setattr(hcr, "LOG", tmp_path / "run.log")

    def fake_process(_tab, card: dict, idx: int, **_kwargs) -> dict:
        _kwargs["live_check"](_tab)
        opened.append(card["url"])
        return _row(card, idx)

    monkeypatch.setattr(hcr, "process_profile", fake_process)

    with pytest.raises(ProfileLockError, match="owner activity"):
        hcr.process_cards_with_r4(
            FakeTab(),
            _cards(3),
            owner_snapshot=lambda: next(snapshots),
            live_check=lambda _tab: {"ok": True},
        )
    assert opened == ["https://www.linkedin.com/talent/profile/000"]
    saved = json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))
    assert [row["url"] for row in saved] == ["https://www.linkedin.com/talent/profile/000"]


def test_no_owner_activity_processes_all_cards(monkeypatch, tmp_path: Path) -> None:
    opened: list[str] = []
    monkeypatch.setattr(hcr, "OUT_DIR", tmp_path)
    monkeypatch.setattr(hcr, "LOG", tmp_path / "run.log")

    def fake_process(_tab, card: dict, idx: int, **_kwargs) -> dict:
        opened.append(card["url"])
        return _row(card, idx)

    monkeypatch.setattr(hcr, "process_profile", fake_process)

    rows = hcr.process_cards_with_r4(
        FakeTab(),
        _cards(3),
        owner_snapshot=lambda: Snapshot(False),
        live_check=lambda _tab: {"ok": True},
    )

    assert [row["url"] for row in rows] == [card["url"] for card in _cards(3)]
    assert opened == [card["url"] for card in _cards(3)]


def test_mid_run_preflight_error_stops_without_opening_remaining(monkeypatch, tmp_path: Path) -> None:
    opened: list[str] = []
    checks = {"count": 0}
    monkeypatch.setattr(hcr, "OUT_DIR", tmp_path)
    monkeypatch.setattr(hcr, "LOG", tmp_path / "run.log")

    def fake_process(_tab, card: dict, idx: int, **_kwargs) -> dict:
        _kwargs["live_check"](_tab)
        opened.append(card["url"])
        return _row(card, idx)

    def fake_live_check(_tab):
        checks["count"] += 1
        if checks["count"] == 2:
            raise PreflightError(
                {
                    "ok": False,
                    "reasons": ["캡차/보안 체크포인트 감지"],
                    "checks": {},
                    "card_count": 1,
                }
            )
        return {"ok": True}

    monkeypatch.setattr(hcr, "process_profile", fake_process)

    rows = hcr.process_cards_with_r4(
        FakeTab(),
        _cards(4),
        owner_snapshot=lambda: Snapshot(False),
        live_check=fake_live_check,
    )

    assert [row["url"] for row in rows] == [
        "https://www.linkedin.com/talent/profile/000",
    ]
    assert opened == [
        "https://www.linkedin.com/talent/profile/000",
    ]
    assert checks["count"] == 2


def test_main_passes_owner_snapshot_into_r4_loop(monkeypatch, tmp_path: Path) -> None:
    tab = FakeTab()
    calls: list[object] = []
    sentinel = lambda: Snapshot(False)

    monkeypatch.setattr(hcr, "OUT_DIR", tmp_path)
    monkeypatch.setattr(hcr, "LOG", tmp_path / "run.log")
    monkeypatch.setattr(
        hcr,
        "resolve_exact_recruiter_target",
        lambda **_kwargs: {"id": "t1", "url": hcr.SEARCH_URL_BASE},
    )
    monkeypatch.setattr(hcr.cdp, "new_tab", lambda _url: {"targetId": "new"})
    monkeypatch.setattr(hcr.cdp, "attach", lambda _target, **_kwargs: tab)
    monkeypatch.setattr(hcr, "navigate_results_page", lambda _tab, _start, **_kwargs: None)
    monkeypatch.setattr(hcr, "assert_not_blocked_or_abort", lambda _tab: {"ok": True})
    monkeypatch.setattr(hcr, "assert_live_or_abort", lambda _tab: {"ok": True})
    monkeypatch.setattr(hcr, "read_result_count", lambda _tab: 5)
    monkeypatch.setattr(hcr, "extract_cards_from_current_page", lambda _tab, **_kwargs: [])
    monkeypatch.setattr(hcr, "iter_planned_cards", lambda _tab, **_kwargs: _cards(2))

    def fake_process_cards(
        _tab, cards, *, owner_snapshot, live_check, mutation_guard, badge_guard
    ):
        calls.append(owner_snapshot)
        assert live_check is hcr.assert_not_blocked_or_abort
        mutation_guard()
        badge_guard(_tab)
        return [_row(card, idx) for idx, card in enumerate(cards, 1)]

    monkeypatch.setattr(hcr, "process_cards_with_r4", fake_process_cards)

    hcr.main(owner_snapshot=sentinel, mutation_sleep=lambda _seconds: None)

    assert calls == [sentinel]
    assert tab.closed is True


def test_no_legacy_max_profile_slice_reintroduced() -> None:
    source = Path(hcr.__file__).read_text(encoding="utf-8")
    assert "cards[:max_profiles]" not in source
