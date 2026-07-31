"""2026-07-31 전수 리뷰 — M6 서울 4년제 목록 · F11 원장 live 표기 (U13/U18).

goal: docs/engineering/aisearch-review-fix-goal-2026-07-31.md
D2 계약: "서울권대학교" = **서울 소재 4년제 전체**(캠퍼스 소재지 기준, 서열 기준 아님).
"""
from __future__ import annotations

import json

from apps.aisearch.core.data import seoul_universities as mod
from apps.aisearch.core.data.seoul_universities import SEOUL_UNIVERSITIES


# ── M6 — 목록의 전체성 ────────────────────────────────────────────────────

#: 리뷰에서 누락으로 지목된 서울 소재 4년제(각 소재 자치구).
MISSING_IN_REVIEW = {
    "감리교신학대학교": "서대문구",
    "장로회신학대학교": "광진구",
    "한국성서대학교": "노원구",
    "서울기독대학교": "은평구",
}

#: 서울 밖 본교 — 소재지 기준이므로 들어오면 안 된다(counter-AC).
MUST_NOT_CONTAIN = (
    "한국과학기술원",
    "포항공과대학교",
    "인하대학교",
    "아주대학교",
    "가톨릭대학교",  # 본교 부천
    "서울신학대학교",  # 이름에 '서울'이 있으나 본교는 부천
)


def test_m6_previously_missing_seoul_universities_are_included():
    for name in MISSING_IN_REVIEW:
        assert name in SEOUL_UNIVERSITIES, f"서울 소재 4년제 누락: {name}"


def test_m6_non_seoul_campuses_stay_out():
    for name in MUST_NOT_CONTAIN:
        assert name not in SEOUL_UNIVERSITIES, f"서울 밖 본교가 들어왔다: {name}"


def test_m6_entries_are_unique_and_normalised():
    assert len(set(SEOUL_UNIVERSITIES)) == len(SEOUL_UNIVERSITIES), "중복 항목이 있다"
    for name in SEOUL_UNIVERSITIES:
        assert name == name.strip() and name, f"공백/빈 항목: {name!r}"
        assert name.endswith(("대학교", "학교")), f"학교명 형식 위반: {name}"


def test_m6_each_entry_has_a_documented_district():
    """전체성 검증 강화 — 항목마다 소재 자치구 근거가 코드에 남아 있어야 한다."""
    assert hasattr(mod, "SEOUL_UNIVERSITY_DISTRICTS"), (
        "소재지 근거표(SEOUL_UNIVERSITY_DISTRICTS)가 없다"
    )
    districts = mod.SEOUL_UNIVERSITY_DISTRICTS
    assert set(districts) == set(SEOUL_UNIVERSITIES), (
        "목록과 소재지 근거표가 어긋난다: "
        f"{set(SEOUL_UNIVERSITIES) ^ set(districts)}"
    )
    for name, district in districts.items():
        assert district.endswith(("구", "시")), f"{name}: 소재지 표기 이상 — {district}"


def test_m6_count_grew_and_is_reasonable():
    assert len(SEOUL_UNIVERSITIES) >= 39, (
        f"서울 소재 4년제가 너무 적다({len(SEOUL_UNIVERSITIES)}개) — 누락 점검 필요"
    )


# ── F11 — 리포트의 live 표기가 실제 레코더를 반영한다 ──────────────────────


def test_f11_report_reflects_injected_live_recorder(tmp_path, monkeypatch):
    """--live 플래그가 없어도 실제 live 레코더를 주입했으면 원장에 그대로 남는다."""
    from apps.aisearch import run as run_mod
    from apps.aisearch.core.recorders import DualRecorder
    from tests.test_aisearch_run_entrypoint import JD, FakeTransport

    class _Noop:
        def __getattr__(self, item):
            return lambda *a, **k: None

    live_recorder = DualRecorder(
        _Noop(), _Noop(), _Noop(), live=True, owner_signoff=True
    )

    jd_path = tmp_path / "jd.json"
    jd_path.write_text(json.dumps(JD, ensure_ascii=False), encoding="utf-8")
    report_out = tmp_path / "report.json"

    run_mod.main(
        [
            str(jd_path),
            "--browser",  # --live 플래그 없음
            "--ws-url",
            "ws://injected",
            "--pages-out",
            str(tmp_path / "pages.jsonl"),
            "--report-out",
            str(report_out),
        ],
        transport_factory=lambda url: FakeTransport(),
        extractors={ch: (lambda pages: []) for ch in run_mod.CHANNELS},
        recorder=live_recorder,
    )

    payload = json.loads(report_out.read_text(encoding="utf-8"))
    assert payload["live"] is True, (
        "실제 라이브 쓰기가 가능한 레코더인데 원장에는 dry-run 으로 기록됐다"
    )
    assert payload["mode"] == "browser_live"


def test_f11_dry_run_recorder_reports_dry_run(tmp_path):
    from apps.aisearch import run as run_mod
    from tests.test_aisearch_run_entrypoint import JD, FakeTransport

    jd_path = tmp_path / "jd.json"
    jd_path.write_text(json.dumps(JD, ensure_ascii=False), encoding="utf-8")
    report_out = tmp_path / "report.json"

    run_mod.main(
        [
            str(jd_path),
            "--browser",
            "--ws-url",
            "ws://injected",
            "--pages-out",
            str(tmp_path / "pages.jsonl"),
            "--report-out",
            str(report_out),
        ],
        transport_factory=lambda url: FakeTransport(),
        extractors={ch: (lambda pages: []) for ch in run_mod.CHANNELS},
    )

    payload = json.loads(report_out.read_text(encoding="utf-8"))
    assert payload["live"] is False
    assert payload["mode"] == "browser_dry_run"
