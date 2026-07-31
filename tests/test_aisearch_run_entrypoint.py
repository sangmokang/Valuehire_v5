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


@pytest.fixture(autouse=True)
def _structural_evidence_verifier(monkeypatch):
    """영수증 **실물** 무결성은 전용 테스트가 지킨다 — 여기서는 모양 검사로 대체.

    프로덕션 기본값이 정본 검증기(browser_evidence.complete_evidence_payload)라는
    사실은 tests/test_aisearch_v1_round3.py 가 따로 잠근다.
    """
    from tests.aisearch_evidence import use_structural_verifier

    use_structural_verifier(monkeypatch)


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


class TestPerChannelWsUrl:
    """V1 독립검증 결함3 — 실 CDP 경로는 채널당 독립 탭(URL)이 필수다."""

    def test_real_path_rejects_shared_single_ws_url(self, tmp_path, monkeypatch):
        # transport_factory 미주입(실 경로) + 채널별 --ws-url-<channel> 없이
        # 공용 --ws-url 만 주면 fail-closed 로 거부해야 한다(같은 탭 공유 금지).
        monkeypatch.setattr(run_mod, "connect_websocket_transport", lambda url: FakeTransport())
        with pytest.raises(SystemExit):
            run_mod.main(
                [
                    _write_jd(tmp_path),
                    "--browser",
                    "--ws-url",
                    "ws://shared-tab",
                    "--pages-out",
                    str(tmp_path / "pages.jsonl"),
                ],
                extractors=_empty_extractors(),
            )

    def test_real_path_rejects_duplicate_per_channel_urls(self, tmp_path, monkeypatch):
        monkeypatch.setattr(run_mod, "connect_websocket_transport", lambda url: FakeTransport())
        with pytest.raises(SystemExit):
            run_mod.main(
                [
                    _write_jd(tmp_path),
                    "--browser",
                    "--ws-url-linkedin_rps",
                    "ws://same",
                    "--ws-url-saramin",
                    "ws://same",  # 링크드인과 동일 — 탭 공유, fail-closed 대상
                    "--ws-url-jobkorea",
                    "ws://jobkorea-tab",
                    "--pages-out",
                    str(tmp_path / "pages.jsonl"),
                ],
                extractors=_empty_extractors(),
            )

    def test_real_path_accepts_three_distinct_per_channel_urls(self, tmp_path, monkeypatch):
        connected_urls: list[str] = []

        def fake_connect(url: str) -> FakeTransport:
            connected_urls.append(url)
            return FakeTransport()

        monkeypatch.setattr(run_mod, "connect_websocket_transport", fake_connect)
        monkeypatch.setenv("AISEARCH_LINKEDIN_LOCK_DIR", str(tmp_path / "shared-lock-storage"))
        code = run_mod.main(
            [
                _write_jd(tmp_path),
                "--browser",
                "--ws-url-linkedin_rps",
                "ws://linkedin-tab",
                "--ws-url-saramin",
                "ws://saramin-tab",
                "--ws-url-jobkorea",
                "ws://jobkorea-tab",
                "--pages-out",
                str(tmp_path / "pages.jsonl"),
            ],
            extractors=_empty_extractors(),
        )
        assert code == 0
        # 3채널 각자 다른 URL로 접속했는지 확인(같은 탭 공유 0건).
        assert sorted(connected_urls) == [
            "ws://jobkorea-tab",
            "ws://linkedin-tab",
            "ws://saramin-tab",
        ]


class TestLiveGateReachesAdminStep:
    """V1 독립검증 결함2 — 실 recorder 를 주입하면 --live 가 더 이상 항상 거부하지 않는다."""

    def test_live_with_real_recorder_injected_is_not_rejected(self, tmp_path):
        from apps.aisearch.core.recorders import DualRecorder

        class _FakeClickUp:
            def find_parent_task(self, list_id, position_name):
                return "parent-1"

            def subtask_exists_with_profile_url(self, list_id, profile_url):
                return False

            def create_parent_task(self, list_id, position_name):
                return "parent-1"

            def create_candidate_subtask(self, list_id, parent_task_id, fields):
                return "subtask-1"

        class _FakeDiscord:
            def post_message(self, channel_id, content):
                return "msg-1"

        class _FakeAdmin:
            def __init__(self):
                self.calls = 0

            def register_candidate(self, payload):
                self.calls += 1
                return {"ok": True, "candidate": {"id": "x"}, "deduped": False}

        admin = _FakeAdmin()
        real_recorder = DualRecorder(
            _FakeClickUp(), _FakeDiscord(), admin, live=True, owner_signoff=True
        )

        # 후보 0명이어도(추출기 빈 목록) --live 자체가 exit(2) 로 거부되지 않아야
        # 한다 — 이전에는 recorder 주입 여부와 무관하게 항상 거부했다(결함2).
        code = run_mod.main(
            [
                _write_jd(tmp_path),
                "--browser",
                "--ws-url",
                "ws://injected-not-used",
                "--pages-out",
                str(tmp_path / "pages.jsonl"),
                "--live",
            ],
            transport_factory=lambda ws_url: FakeTransport(),
            extractors=_empty_extractors(),
            recorder=real_recorder,
        )
        assert code == 0  # exit(2) 로 거부되지 않았다 — 게이트 통과 증명

    def test_live_with_recorder_not_configured_for_live_still_rejected(self, tmp_path):
        from apps.aisearch.core.recorders import DualRecorder

        class _Noop:
            def __getattr__(self, item):
                raise AssertionError(f"미구성 클라이언트 호출됨: {item}")

        dry_run_recorder = DualRecorder(_Noop(), _Noop())  # live=False(기본)

        with pytest.raises(SystemExit) as exc:
            run_mod.main(
                [_write_jd(tmp_path), "--browser", "--ws-url", "ws://x", "--live"],
                transport_factory=lambda ws_url: FakeTransport(),
                extractors=_empty_extractors(),
                recorder=dry_run_recorder,  # 주입은 했지만 live=False — 플래그 불일치
            )
        assert exc.value.code not in (0, None)


class TestLinkedInLockRequiredOnRealPath:
    """V1 2차 독립검증 결함4 — 실 경로에서 락 미설정은 조용히 진행이 아니라 거부."""

    def test_real_path_without_lock_dir_env_is_rejected(self, tmp_path, monkeypatch):
        monkeypatch.delenv("AISEARCH_LINKEDIN_LOCK_DIR", raising=False)
        monkeypatch.setattr(run_mod, "connect_websocket_transport", lambda url: FakeTransport())

        with pytest.raises(SystemExit) as exc:
            run_mod.main(
                [
                    _write_jd(tmp_path),
                    "--browser",
                    "--ws-url-linkedin_rps",
                    "ws://linkedin-tab",
                    "--ws-url-saramin",
                    "ws://saramin-tab",
                    "--ws-url-jobkorea",
                    "ws://jobkorea-tab",
                    "--pages-out",
                    str(tmp_path / "pages.jsonl"),
                ],
                extractors=_empty_extractors(),
            )
        assert exc.value.code not in (0, None)

    def test_test_injected_transport_path_does_not_require_lock_env(self, tmp_path, monkeypatch):
        # transport_factory 를 직접 주입하는(테스트) 경로는 실 CDP 경로가 아니므로
        # 락 env 강제 대상이 아니다 — 이 요구가 테스트 전반을 깨면 안 된다.
        monkeypatch.delenv("AISEARCH_LINKEDIN_LOCK_DIR", raising=False)
        code = run_mod.main(
            [
                _write_jd(tmp_path),
                "--browser",
                "--ws-url",
                "ws://injected-not-used",
                "--pages-out",
                str(tmp_path / "pages.jsonl"),
            ],
            transport_factory=lambda ws_url: FakeTransport(),
            extractors=_empty_extractors(),
        )
        assert code == 0


class TestProfileUrlValidationHardened:
    """V1 2차 독립검증 결함8 — 스킴만 보는 정규식은 호스트 없는 URL을 통과시켰다."""

    def test_scheme_only_url_without_host_is_rejected(self):
        from apps.aisearch.core.recorders import _is_valid_http_url

        assert _is_valid_http_url("https://") is False
        assert _is_valid_http_url("http://") is False

    def test_url_with_internal_whitespace_is_rejected(self):
        from apps.aisearch.core.recorders import _is_valid_http_url

        assert _is_valid_http_url("https://a b.com/profile") is False

    def test_valid_urls_still_accepted(self):
        from apps.aisearch.core.recorders import _is_valid_http_url

        assert _is_valid_http_url("https://www.linkedin.com/in/hong-gildong/") is True
        assert _is_valid_http_url("http://example.com") is True

    def test_javascript_scheme_still_rejected(self):
        from apps.aisearch.core.recorders import _is_valid_http_url

        assert _is_valid_http_url("javascript:void(0)") is False
