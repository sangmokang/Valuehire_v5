"""V1 3차 결함 ④ — 프로덕션 엔트리포인트 apps/aisearch/run.py 조립 경로 검증.

run.py 는 JD 파일 경로를 받아 cdp_driver + run_search_pipeline 을 조립한다.
기본 dry-run(외부 기록 0), --live 는 명시 플래그(기록 클라이언트 미구성이면
fail-closed 거부). 이 테스트는 페이크 트랜스포트 팩토리를 주입해 실 브라우저/
웹소켓(9222) 접속 없이 조립 경로 전체를 검증한다.
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

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, method: str, params: dict) -> dict:
        self.calls.append((method, dict(params)))
        if method == "Page.navigate":
            return {"frameId": "F1", "loaderId": "L1"}
        expr = params.get("expression", "")
        value: object = True
        if "/*vh:count*/" in expr:
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
            value = {"h": 0, "captcha": False, "cloudflare": False}
        return {"result": {"value": value}}


def _write_jd(tmp_path) -> str:
    jd_path = tmp_path / "jd.json"
    jd_path.write_text(json.dumps(JD, ensure_ascii=False), encoding="utf-8")
    return str(jd_path)


class TestRunAssembly:
    def test_dry_run_assembles_driver_and_pipeline(self, tmp_path):
        transport = FakeTransport()
        pages_out = tmp_path / "pages.jsonl"
        report_out = tmp_path / "report.json"
        code = run_mod.main(
            [
                _write_jd(tmp_path),
                "--ws-url",
                "ws://injected-not-used",
                "--machine",
                "macmini",
                "--pages-out",
                str(pages_out),
                "--report-out",
                str(report_out),
            ],
            transport_factory=lambda ws_url: transport,
        )
        assert code == 0
        report = json.loads(report_out.read_text(encoding="utf-8"))
        assert report["status"] == "completed"
        assert report["live"] is False  # 기본 dry-run
        # 전량 저장이 로컬 jsonl 로 남는다 — 3채널 전부 실행됨
        rows = [
            json.loads(line)
            for line in pages_out.read_text(encoding="utf-8").splitlines()
        ]
        assert rows, "저장된 페이지 행이 없다"
        channels = {row["channel"] for row in rows}
        assert channels == {"linkedin_rps", "saramin", "jobkorea"}
        # 실제 브라우저 실행 호출부: 사람인/잡코리아 URL 이동 + RPS Boolean fill
        navigated = [
            p["url"] for m, p in transport.calls if m == "Page.navigate"
        ]
        assert any("saramin.co.kr" in u for u in navigated)
        assert any("jobkorea.co.kr" in u for u in navigated)
        fills = [
            p.get("expression", "")
            for m, p in transport.calls
            if m == "Runtime.evaluate" and "/*vh:fill*/" in p.get("expression", "")
        ]
        # RPS Boolean 키워드 입력 — fill JS 는 json.dumps(ensure_ascii=True)로
        # 이스케이프하므로 한글은 \uXXXX 형태로 실린다.
        escaped_keyword = json.dumps("백엔드")[1:-1]
        assert any(escaped_keyword in f for f in fills)

    def test_live_flag_without_record_clients_fails_closed(self, tmp_path):
        with pytest.raises(SystemExit) as exc:
            run_mod.main(
                [_write_jd(tmp_path), "--ws-url", "ws://x", "--live"],
                transport_factory=lambda ws_url: FakeTransport(),
            )
        assert exc.value.code not in (0, None)

    def test_missing_ws_url_without_factory_fails_closed(self, tmp_path):
        with pytest.raises(SystemExit):
            run_mod.main([_write_jd(tmp_path)])

    def test_blocked_pipeline_returns_nonzero(self, tmp_path):
        class CaptchaTransport(FakeTransport):
            def __call__(self, method: str, params: dict) -> dict:
                if "/*vh:snapshot*/" in params.get("expression", ""):
                    self.calls.append((method, dict(params)))
                    return {
                        "result": {
                            "value": {
                                "h": 0,
                                "captcha": True,
                                "cloudflare": False,
                            }
                        }
                    }
                return super().__call__(method, params)

        report_out = tmp_path / "report.json"
        code = run_mod.main(
            [
                _write_jd(tmp_path),
                "--ws-url",
                "ws://x",
                "--report-out",
                str(report_out),
            ],
            transport_factory=lambda ws_url: CaptchaTransport(),
        )
        assert code != 0
        report = json.loads(report_out.read_text(encoding="utf-8"))
        assert report["status"] == "blocked"
