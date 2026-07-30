"""V1 3차 결함 ④(+4차 진입점 결함) — apps/aisearch/run.py 조립 경로 검증.

run.py 는 JD 파일 경로를 받아 cdp_driver + run_search_pipeline 을 조립한다.
4차 재설계: 기본 = plan-only(브라우저 무접촉), --browser = 부착 dry-run(외부
기록 0, 채널당 독립 드라이버 + 추출기 필수), --live = 오너 승인 게이트(거부).
이 테스트는 페이크 트랜스포트 팩토리를 주입해 실 브라우저/웹소켓(9222) 접속
없이 조립 경로 전체를 검증한다(실 sleep 0 — 페이크는 즉시 complete 응답).
"""
from __future__ import annotations

import json

import pytest

from apps.aisearch import run as run_mod


JD = {
    "position_name": "Tech PM",
    "keyword_groups": [["백엔드", "Backend"], ["PM"]],
    "requirements": {"min_years": 3},
    "or_keywords": ["백엔드", "Backend"],
    "and_keywords": ["Python"],
    "career_min": 3,
    "career_max": 10,
}


class FakeTransport:
    """실 브라우저 없는 패턴 응답 트랜스포트 — 전 채널 1페이지 소진 시나리오."""

    SNAPSHOT = {
        "h": 0,
        "captcha": False,
        "cloudflare": False,
        "twofa": False,
        "checkpoint": False,
        "multisession": False,
        "present": True,
    }

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, method: str, params: dict) -> dict:
        self.calls.append((method, dict(params)))
        if method == "Page.navigate":
            return {"frameId": "F1", "loaderId": "L1"}
        if method.startswith("Input."):
            return {}
        expr = params.get("expression", "")
        value: object = True
        if "/*vh:ready*/" in expr:
            value = "complete"
        elif "/*vh:rect*/" in expr:
            value = {"x": 100.0, "y": 40.0}
        elif "/*vh:count*/" in expr:
            value = "12명"
        elif "/*vh:html*/" in expr:
            value = "<html>captured</html>"
        elif "/*vh:url*/" in expr:
            value = "https://fake.test/list"
        elif "/*vh:detail_refs*/" in expr:
            value = []
        elif "/*vh:has_next*/" in expr:
            value = False
        elif "/*vh:snapshot*/" in expr:
            value = dict(FakeTransport.SNAPSHOT)
        return {"result": {"value": value}}


def _write_jd(tmp_path) -> str:
    jd_path = tmp_path / "jd.json"
    jd_path.write_text(json.dumps(JD, ensure_ascii=False), encoding="utf-8")
    return str(jd_path)


def _empty_extractors():
    return {ch: (lambda pages: []) for ch in run_mod.CHANNELS}


class TestRunAssembly:
    def test_browser_dry_run_assembles_driver_and_pipeline(self, tmp_path):
        transports: list[FakeTransport] = []

        def factory(ws_url: str) -> FakeTransport:
            t = FakeTransport()
            transports.append(t)
            return t

        pages_out = tmp_path / "pages.jsonl"
        report_out = tmp_path / "report.json"
        code = run_mod.main(
            [
                _write_jd(tmp_path),
                "--browser",
                "--ws-url",
                "ws://injected-not-used",
                "--machine",
                "macmini",
                "--pages-out",
                str(pages_out),
                "--report-out",
                str(report_out),
            ],
            transport_factory=factory,
            extractors=_empty_extractors(),
        )
        assert code == 0
        report = json.loads(report_out.read_text(encoding="utf-8"))
        assert report["status"] == "completed"
        assert report["mode"] == "browser_dry_run"
        assert report["live"] is False  # 외부 기록 0
        # 4차 결함 ⑩ — 채널당 독립 드라이버(연결) 3개.
        assert len(transports) == 3
        # 전량 저장이 로컬 jsonl 로 남는다 — 3채널 전부 실행됨
        rows = [
            json.loads(line)
            for line in pages_out.read_text(encoding="utf-8").splitlines()
        ]
        assert rows, "저장된 페이지 행이 없다"
        channels = {row["channel"] for row in rows}
        assert channels == {"linkedin_rps", "saramin", "jobkorea"}
        # 실제 브라우저 실행 호출부: 사람인/잡코리아 URL 이동 + RPS 신뢰 입력
        all_calls = [c for t in transports for c in t.calls]
        navigated = [p["url"] for m, p in all_calls if m == "Page.navigate"]
        assert any("saramin.co.kr" in u for u in navigated)
        assert any("jobkorea.co.kr" in u for u in navigated)
        inserted = [p["text"] for m, p in all_calls if m == "Input.insertText"]
        assert any("백엔드" in text for text in inserted)  # CDP Input 신뢰 입력

    def test_live_flag_without_record_clients_fails_closed(self, tmp_path):
        with pytest.raises(SystemExit) as exc:
            run_mod.main(
                [_write_jd(tmp_path), "--browser", "--ws-url", "ws://x", "--live"],
                transport_factory=lambda ws_url: FakeTransport(),
                extractors=_empty_extractors(),
            )
        assert exc.value.code not in (0, None)

    def test_browser_without_ws_url_and_factory_fails_closed(self, tmp_path):
        with pytest.raises(SystemExit):
            run_mod.main(
                [_write_jd(tmp_path), "--browser"],
                extractors=_empty_extractors(),
            )

    def test_default_mode_never_needs_ws_url(self, tmp_path):
        # 기본 plan-only — ws-url/트랜스포트 없이 성공(브라우저 무접촉).
        code = run_mod.main([_write_jd(tmp_path)])
        assert code == 0

    def test_blocked_pipeline_returns_nonzero(self, tmp_path):
        class CaptchaTransport(FakeTransport):
            def __call__(self, method: str, params: dict) -> dict:
                if "/*vh:snapshot*/" in params.get("expression", ""):
                    self.calls.append((method, dict(params)))
                    snap = dict(FakeTransport.SNAPSHOT)
                    snap["captcha"] = True
                    return {"result": {"value": snap}}
                return super().__call__(method, params)

        report_out = tmp_path / "report.json"
        code = run_mod.main(
            [
                _write_jd(tmp_path),
                "--browser",
                "--ws-url",
                "ws://x",
                "--pages-out",
                str(tmp_path / "pages.jsonl"),
                "--report-out",
                str(report_out),
            ],
            transport_factory=lambda ws_url: CaptchaTransport(),
            extractors=_empty_extractors(),
        )
        assert code != 0
        report = json.loads(report_out.read_text(encoding="utf-8"))
        assert report["status"] == "blocked"
