from __future__ import annotations

from pathlib import Path

import pytest

from tools.multi_position_sourcing import humansearch_cdp_run as hcr


def test_profile_delay_draws_fresh_180_to_420_seconds(monkeypatch):
    values = iter((180.0, 231.5, 419.9))
    calls = []
    monkeypatch.setattr(hcr.random, "uniform", lambda lo, hi: (calls.append((lo, hi)), next(values))[1])
    sleeps = []
    monkeypatch.setattr(hcr.time, "sleep", sleeps.append)
    hcr.human_delay()
    hcr.human_delay()
    hcr.human_delay()
    assert calls == [(180.0, 420.0)] * 3
    assert sleeps == [180.0, 231.5, 419.9]


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


def _cards(start: int, count: int) -> list[dict]:
    return [
        {
            "url": f"https://www.linkedin.com/talent/profile/{idx:03d}",
            "name": f"candidate-{idx:03d}",
        }
        for idx in range(start, start + count)
    ]


def test_full_gold_traversal_collects_all_60_not_first_25(monkeypatch) -> None:
    starts: list[int] = []
    delay_calls: list[tuple[str, int, int]] = []
    sleeps: list[float] = []
    pages = {0: _cards(0, 25), 25: _cards(25, 25), 50: _cards(50, 10)}

    def fake_collect(_tab, start: int) -> list[dict]:
        starts.append(start)
        return pages[start]

    def fake_delay(*, kind: str, step: int, seed: int) -> int:
        delay_calls.append((kind, step, seed))
        return step * 100

    monkeypatch.setattr(hcr, "collect_cards", fake_collect)
    monkeypatch.setattr(hcr, "deterministic_delay_ms", fake_delay, raising=False)
    monkeypatch.setattr(hcr.time, "sleep", lambda seconds: sleeps.append(seconds))

    cards = hcr.iter_planned_cards(FakeTab(), result_count=60, pacing_seed=7)

    assert len(cards) == 60
    assert starts == [0, 25, 50]
    assert delay_calls == [("short", 1, 7), ("short", 2, 7)]
    assert sleeps == [0.1, 0.2]
    assert cards[-1]["url"].endswith("/059")


def test_top_n_traversal_stops_at_limit_without_fetching_extra_page(monkeypatch) -> None:
    starts: list[int] = []

    def fake_collect(_tab, start: int) -> list[dict]:
        starts.append(start)
        return _cards(start, 25)

    monkeypatch.setattr(hcr, "collect_cards", fake_collect)

    cards = hcr.iter_planned_cards(FakeTab(), result_count=61)

    assert len(cards) == 20
    assert starts == [0]
    assert cards[-1]["url"].endswith("/019")


def test_abort_and_add_condition_do_not_collect(monkeypatch) -> None:
    starts: list[int] = []
    monkeypatch.setattr(hcr, "collect_cards", lambda _tab, start: starts.append(start) or [])

    assert hcr.iter_planned_cards(FakeTab(), result_count=4) == []
    assert hcr.iter_planned_cards(FakeTab(), result_count=201) == []
    assert starts == []


def test_full_traversal_dedupes_across_pages(monkeypatch) -> None:
    starts: list[int] = []
    pages = {
        0: _cards(0, 3),
        3: [
            {"url": "https://www.linkedin.com/talent/profile/002", "name": "duplicate"},
            {"url": "https://www.linkedin.com/talent/profile/003", "name": "candidate-003"},
            {"url": "https://www.linkedin.com/talent/profile/004", "name": "candidate-004"},
        ],
    }

    def fake_collect(_tab, start: int) -> list[dict]:
        starts.append(start)
        return pages[start]

    monkeypatch.setattr(hcr, "collect_cards", fake_collect)
    monkeypatch.setattr(hcr.time, "sleep", lambda _seconds: None)

    cards = hcr.iter_planned_cards(FakeTab(), result_count=5, page_size=3)

    assert [card["url"].rsplit("/", 1)[1] for card in cards] == ["000", "001", "002", "003", "004"]
    assert starts == [0, 3]


def test_main_uses_planned_traversal_path(monkeypatch, tmp_path: Path) -> None:
    tab = FakeTab()
    calls: list[dict] = []
    processed: list[str] = []

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
    monkeypatch.setattr(hcr, "extract_cards_from_current_page", lambda _tab, **_kwargs: [])
    monkeypatch.setattr(hcr, "assert_not_blocked_or_abort", lambda _tab: {"ok": True})
    monkeypatch.setattr(hcr, "assert_live_or_abort", lambda _tab: {"ok": True})
    monkeypatch.setattr(hcr, "read_result_count", lambda _tab: 60, raising=False)

    def fake_iter(_tab, **kwargs) -> list[dict]:
        calls.append(kwargs)
        return _cards(0, 3)

    def fake_process(
        _tab, card: dict, idx: int, *, live_check=None, mutation_guard=None,
        badge_guard=None,
    ) -> dict:
        assert live_check is hcr.assert_not_blocked_or_abort
        mutation_guard()
        badge_guard(_tab)
        processed.append(card["url"])
        return {
            "idx": idx,
            "name": card["name"],
            "url": card["url"],
            "hard_exclude": None,
            "score": 70,
            "otw": False,
            "education": "",
        }

    monkeypatch.setattr(hcr, "iter_planned_cards", fake_iter, raising=False)
    monkeypatch.setattr(hcr, "process_profile", fake_process)
    monkeypatch.setattr(hcr, "human_delay", lambda: None)

    hcr.main(owner_snapshot=lambda: type("Snapshot", (), {"owner_activity_detected": False})())

    assert calls
    assert calls[0]["result_count"] == 60
    assert calls[0]["channel"] == "linkedin"
    assert processed == [card["url"] for card in _cards(0, 3)]
    assert tab.closed is True


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("60 results", 60),
        ("3.9K+ results", 3900),
        ("총 42명", 42),
    ],
)
def test_parse_result_count_supported_formats(raw: str, expected: int) -> None:
    assert hcr._parse_result_count(raw) == expected


def test_parse_result_count_fails_closed_on_missing_number() -> None:
    with pytest.raises(ValueError):
        hcr._parse_result_count("Loading results")
