"""V1 4차 적대검증 STILL-BROKEN 재현 — 결함 ①②④⑦⑩ + 진입점 결함 3건.

① RPS 입력이 JS 합성(value 대입) → CDP Input 도메인 신뢰 입력 + 필터 실제 실행
② 이동 후 로드 완료 대기 없음 + 잡코리아 체크박스 value 대입
④ 개입 감지 3종(자동 입력 표식 / 이동 후 감시 재설치 / 2FA·체크포인트·멀티세션)
⑦ 제외어가 최상위 문자열만 검사됨 → payload 전체 재귀 스캔
⑩ 단일 탭·단일 연결 공유 → 채널별 드라이버 + 연결 단위 락
run.py:46,171 — --live 없이도 실 브라우저 접속 → 3단계 모드(기본 plan-only)
run.py:87 — 후보 추출기 항상 0명 → 추출기 필수 + 저장 HTML 배선

전부 페이크 트랜스포트 — 실 브라우저/웹소켓(9222) 접속 0, 실 sleep 0.
"""
from __future__ import annotations

import json
import threading

import pytest

from test_aisearch_orchestrator import (
    PAYLOAD_60,
    FakeClickUp,
    FakeDiscord,
    Harness,
    _candidate,
    _jd,
    _score_payload,
)

from apps.aisearch import run as run_mod
from apps.aisearch.core import portal_search
from apps.aisearch.core.cdp_driver import CdpDriver, CdpDriverError
from apps.aisearch.core.intervention import (
    InterventionMonitor,
    MonitorState,
    feed_driver_events,
)
from apps.aisearch.core.orchestrator import (
    LINKEDIN_CHANNEL,
    STATUS_COMPLETED,
    PipelineDeps,
    run_search_pipeline,
)
from apps.aisearch.core.recorders import DualRecorder

CHANNELS = (LINKEDIN_CHANNEL, "saramin", "jobkorea")


class FakeTransport:
    """페이크 CDP 트랜스포트 — 전 명령 기록 + 패턴 응답(신 스냅샷 계약)."""

    SNAPSHOT = {
        "h": 0,
        "captcha": False,
        "cloudflare": False,
        "twofa": False,
        "checkpoint": False,
        "multisession": False,
        "present": True,
    }

    def __init__(self, responder=None):
        self.calls: list[tuple[str, dict]] = []
        self._responder = responder or self.default_responder

    @staticmethod
    def default_responder(method: str, params: dict):
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
            value = "1,234명"
        elif "/*vh:html*/" in expr:
            value = "<html>fake</html>"
        elif "/*vh:url*/" in expr:
            value = "https://fake.test/list?p=1"
        elif "/*vh:detail_refs*/" in expr:
            value = []
        elif "/*vh:has_next*/" in expr:
            value = False
        elif "/*vh:snapshot*/" in expr:
            value = dict(FakeTransport.SNAPSHOT)
        return {"result": {"value": value}}

    def __call__(self, method: str, params: dict) -> dict:
        self.calls.append((method, dict(params)))
        return self._responder(method, params)

    def exprs(self) -> list[str]:
        return [
            p.get("expression", "")
            for m, p in self.calls
            if m == "Runtime.evaluate"
        ]

    def inserted_texts(self) -> list[str]:
        return [p["text"] for m, p in self.calls if m == "Input.insertText"]


def _driver(responder=None, **kwargs) -> tuple[CdpDriver, FakeTransport]:
    t = FakeTransport(responder)
    kwargs.setdefault("sleep", lambda s: None)
    return CdpDriver(t, **kwargs), t


def _snapshot_responder(overrides_list):
    """snapshot 응답을 순서대로 바꿔치기하는 responder."""
    seq = iter(overrides_list)

    def responder(method, params):
        if "/*vh:snapshot*/" in params.get("expression", ""):
            snap = dict(FakeTransport.SNAPSHOT)
            try:
                snap.update(next(seq))
            except StopIteration:
                pass
            return {"result": {"value": snap}}
        return FakeTransport.default_responder(method, params)

    return responder


# ── 결함 ① — CDP Input 도메인 신뢰 입력 + RPS 필터 실제 실행 ────────────────


class TestTrustedInputSequence:
    def test_rps_boolean_typed_via_input_domain(self):
        driver, t = _driver()
        boolean = '("백엔드" OR "Backend") NOT ("인턴")'
        count = driver.run_rps_search(boolean)
        assert count == 1234
        # Boolean 문자열은 JS value 대입이 아니라 Input.insertText 로 입력된다.
        assert boolean in t.inserted_texts()
        # 검색 실행은 Input.dispatchKeyEvent(Enter) 시퀀스다.
        keys = [p for m, p in t.calls if m == "Input.dispatchKeyEvent"]
        assert any(p.get("key") == "Enter" for p in keys)
        # 합성 입력(value 대입 + input/change dispatch)이 남아 있으면 결함.
        assert not any(
            ".value=" in e for e in t.exprs() if "/*vh:select*/" not in e
        ), "RPS 입력에 JS value 대입 합성 입력이 남아 있다(결함 ①)"

    def test_rps_filters_are_executed_not_just_carried(self):
        driver, t = _driver()
        payload = {
            "channel": LINKEDIN_CHANNEL,
            "stage": "seoul_university_priority",
            "keywords": '("PM")',
            "location": "South Korea",
            "required_filters": {"min_years": 3},
            "universities": ("서울대학교", "연세대학교"),
        }
        driver.execute_search(payload)
        texts = t.inserted_texts()
        # 지역·대학·경력 필터가 "전달"이 아니라 명령 시퀀스로 실제 실행된다.
        assert "South Korea" in texts, "지역 필터가 실행되지 않았다(결함 ①)"
        assert "서울대학교" in texts and "연세대학교" in texts, (
            "대학 필터가 실행되지 않았다(결함 ①)"
        )
        assert "3" in texts, "경력(min_years) 필터가 실행되지 않았다(결함 ①)"


# ── 결함 ② — 이동 후 로드 완료 대기 + 잡코리아 체크박스 클릭 시퀀스 ─────────


class TestLoadWaitAndCheckbox:
    def test_portal_steps_declare_input_kind(self):
        descs = portal_search.build_portal_search_descriptors(
            or_keywords=["PM"], career_min=3, career_max=10
        )
        jk = next(d for d in descs if d["channel"] == "jobkorea")
        jk_steps = {s["field"]: s for s in jk["steps"]}
        assert jk_steps["education"]["kind"] == "checkbox"
        assert jk_steps["keyword"]["kind"] == "text"
        sar = next(d for d in descs if d["channel"] == "saramin")
        sar_steps = {s["field"]: s for s in sar["steps"]}
        assert sar_steps["career_min"]["kind"] == "select"
        assert sar_steps["or_keywords"]["kind"] == "text"

    def test_checkbox_step_clicked_via_mouse_events(self):
        driver, t = _driver()
        descriptor = {
            "channel": "jobkorea",
            "url": "https://www.jobkorea.co.kr/Corp/Person/Find",
            "steps": [
                {
                    "order": 1,
                    "field": "education",
                    "selector": "#education1",
                    "values": ["대학교(4년) 졸업"],
                    "kind": "checkbox",
                }
            ],
        }
        driver.run_descriptor(descriptor)
        mouse_types = [
            p.get("type") for m, p in t.calls if m == "Input.dispatchMouseEvent"
        ]
        assert "mousePressed" in mouse_types and "mouseReleased" in mouse_types, (
            "체크박스가 클릭 이벤트 시퀀스로 조작되지 않았다(결함 ②)"
        )
        assert not any(
            "#education1" in e and ".value=" in e for e in t.exprs()
        ), "체크박스에 value 대입이 남아 있다(결함 ②)"

    def test_detail_navigation_waits_for_load_before_reading(self):
        driver, t = _driver()
        driver.fetch_detail_page("saramin", "https://fake.test/p/1")
        seq = [
            (m, p.get("expression", "")) for m, p in t.calls
        ]
        nav_i = next(i for i, (m, _e) in enumerate(seq) if m == "Page.navigate")
        ready_i = next(
            i for i, (_m, e) in enumerate(seq) if "/*vh:ready*/" in e
        )
        html_i = next(i for i, (_m, e) in enumerate(seq) if "/*vh:html*/" in e)
        assert nav_i < ready_i < html_i, (
            "이동 후 로드 완료 대기 없이 즉시 HTML 을 읽었다(결함 ②/⑧)"
        )

    def test_next_page_click_waits_for_load_before_reading(self):
        driver, t = _driver()
        payload = {
            "channel": "saramin",
            "url": "https://www.saramin.co.kr/x",
            "steps": [],
            "dedup_key": "k",
            "post_filter_exclude": [],
        }
        driver.fetch_list_page("saramin", 2, payload)
        exprs = t.exprs()
        next_i = next(i for i, e in enumerate(exprs) if "/*vh:next_page*/" in e)
        ready_i = next(
            i for i, e in enumerate(exprs) if "/*vh:ready*/" in e and i > next_i
        )
        html_i = next(i for i, e in enumerate(exprs) if "/*vh:html*/" in e)
        assert next_i < ready_i < html_i

    def test_load_wait_timeout_fails_closed_with_injected_sleep(self):
        def responder(method, params):
            if "/*vh:ready*/" in params.get("expression", ""):
                return {"result": {"value": "loading"}}
            return FakeTransport.default_responder(method, params)

        sleeps: list[float] = []
        driver, _t = _driver(responder, sleep=sleeps.append)
        with pytest.raises(CdpDriverError):
            driver.fetch_detail_page("saramin", "https://fake.test/p/1")
        assert sleeps, "타임아웃 폴링이 주입 sleep 을 쓰지 않았다(실 sleep 금지)"


# ── 결함 ④ — 개입 감지 3종 ─────────────────────────────────────────────────


class TestInterventionUpgrades:
    def test_observer_script_guards_against_automation_marked_input(self):
        driver, t = _driver()
        driver.install_observers()
        observe = next(e for e in t.exprs() if "/*vh:observe*/" in e)
        assert "__vh_auto_active" in observe, (
            "감시 스크립트가 자동 입력 표식을 무시하지 않는다(결함 ④a)"
        )

    def test_automated_input_is_bracketed_with_auto_marker(self):
        driver, t = _driver()
        driver.run_rps_search('("PM")')
        seq: list[str] = []
        for m, p in t.calls:
            e = p.get("expression", "")
            if "/*vh:auto_on*/" in e:
                seq.append("on")
            elif "/*vh:auto_off*/" in e:
                seq.append("off")
            elif m == "Input.insertText":
                seq.append("insert")
        assert "insert" in seq
        first_insert = seq.index("insert")
        assert "on" in seq[:first_insert], (
            "자동 입력 전에 표식(auto_on)이 설정되지 않았다(결함 ④a)"
        )
        assert "off" in seq[first_insert:], (
            "자동 입력 후 표식(auto_off) 해제가 없다(결함 ④a)"
        )

    def test_observers_reinstalled_after_navigation(self):
        driver, t = _driver()
        assert driver.poll_events() == []
        installs = [e for e in t.exprs() if "/*vh:observe*/" in e]
        assert len(installs) == 1
        driver.navigate("https://fake.test/next")
        driver.poll_events()
        installs = [e for e in t.exprs() if "/*vh:observe*/" in e]
        assert len(installs) == 2, (
            "페이지 이동 후 감시 스크립트가 재설치되지 않았다(결함 ④b)"
        )

    def test_snapshot_without_observer_triggers_reinstall(self):
        driver, t = _driver(
            _snapshot_responder([{"present": False}, {}])
        )
        assert driver.poll_events() == []  # 소실 감지 — 사람 입력으로 오인 금지
        installs = [e for e in t.exprs() if "/*vh:observe*/" in e]
        assert len(installs) >= 2, (
            "감시 스크립트 소실(present=false)에도 재설치가 없다(결함 ④b)"
        )

    @pytest.mark.parametrize(
        "field,kind",
        [
            ("twofa", "2fa"),
            ("checkpoint", "checkpoint"),
            ("multisession", "multisession"),
        ],
    )
    def test_challenge_snapshot_fields_emit_blocking_signals(self, field, kind):
        driver, _t = _driver(_snapshot_responder([{field: True}]))
        events = driver.poll_events()
        assert {"type": "signal", "kind": kind} in events, (
            f"{field} 감지가 차단 신호로 발행되지 않았다(결함 ④c)"
        )

        class N:
            def notify(self, message: str) -> None:
                pass

        monitor = InterventionMonitor(lambda: 0.0, N())
        feed_driver_events(monitor, events)
        assert monitor.state is MonitorState.BLOCKED

    def test_challenge_probe_patterns_present_in_snapshot_js(self):
        driver, t = _driver()
        driver.poll_events()
        snapshot_js = next(e for e in t.exprs() if "/*vh:snapshot*/" in e)
        # 2FA·체크포인트·멀티세션 문구 감지 프로브가 실제로 실려 있다.
        for token in ("twofa", "checkpoint", "multisession"):
            assert token in snapshot_js, f"{token} 프로브가 스냅샷 JS 에 없다"


# ── 결함 ⑦ — 후보 payload 전체 재귀 스캔 ───────────────────────────────────


class TestRecursiveExclusionScan:
    def test_exclusion_term_in_score_evidence_blocks_registration(self):
        """점수 근거(D1~D8 evidence)에 '인턴' 포함 → 등록 0·초안 0·excluded 1."""
        h = Harness(pages=1)
        payload = _score_payload()
        payload["dimensions"]["D3"]["evidence"] = "삼성전자 인턴 6개월 경험"
        cand = _candidate(payload, "https://saramin.example/p/deep")
        h.candidates["saramin"] = [cand]
        jd = _jd()
        jd["not_keywords"] = ["인턴"]
        report = run_search_pipeline(jd, h.deps())
        assert report.status == STATUS_COMPLETED
        assert report.registered == [], "점수 근거의 제외어를 놓치고 등록했다(결함 ⑦)"
        assert report.drafts == []
        assert h.clickup.dedup_calls == [] and h.clickup.writes == []
        assert len(report.excluded) == 1
        entry = report.excluded[0]
        assert entry["matched_keyword"] == "인턴"
        assert "score_payload" in entry["matched_field"]

    def test_exclusion_term_in_nested_list_blocks_registration(self):
        h = Harness(pages=1)
        payload = _score_payload()
        payload["gates"] = [
            {"requirement": "req-1", "verdict": "pass", "evidence": "인턴십 수료"}
        ]
        h.candidates["jobkorea"] = [
            _candidate(payload, "https://jk.example/p/nested")
        ]
        jd = _jd()
        jd["not_keywords"] = ["인턴"]
        report = run_search_pipeline(jd, h.deps())
        assert report.registered == [] and report.drafts == []
        assert [e["matched_keyword"] for e in report.excluded] == ["인턴"]


# ── 결함 ⑩ — 채널별 드라이버 + 연결 단위 락 ────────────────────────────────


class _BannerDriver:
    def __init__(self):
        self.snippets: list[str] = []

    def run_js(self, snippet: str) -> None:
        self.snippets.append(snippet)


class TestPerChannelDrivers:
    def test_orchestrator_routes_banner_to_channel_driver(self):
        h = Harness(pages=1)
        dmap = {ch: _BannerDriver() for ch in CHANNELS}
        deps = PipelineDeps(
            driver=h.driver,
            store=h.store,
            monitor=h.monitor,
            recorder=h.recorder,
            fetch_list_page=h.fetch_list_page,
            fetch_detail_page=h.fetch_detail_page,
            extract_candidates=h.extract_candidates,
            machine="macmini",
            poll_driver_events=h.poll_driver_events,
            drivers=dmap,
        )
        report = run_search_pipeline(_jd(), deps)
        assert report.status == STATUS_COMPLETED
        for ch, drv in dmap.items():
            assert drv.snippets, f"{ch} 배너가 채널 드라이버로 가지 않았다(결함 ⑩)"
        assert h.driver.snippets == [], "공용 드라이버로 배너가 샜다(응답 혼선)"

    def test_same_connection_calls_are_serialized_by_lock(self):
        """같은 연결(드라이버)에 대한 동시 호출은 직렬화된다 — 응답 혼선 0."""
        in_first = threading.Event()
        entered_second = threading.Event()
        overlap: list[bool] = []

        class T(FakeTransport):
            def __init__(self):
                super().__init__()
                self._first_seen = False

            def __call__(self, method: str, params: dict) -> dict:
                if not self._first_seen:
                    self._first_seen = True
                    in_first.set()
                    # 첫 호출이 연결을 점유한 동안 두 번째 호출이 진입하는지 관찰
                    overlap.append(entered_second.wait(timeout=1.0))
                else:
                    entered_second.set()
                return super().__call__(method, params)

        t = T()
        driver = CdpDriver(t, sleep=lambda s: None)

        def second():
            in_first.wait(timeout=3.0)
            driver.capture_html()

        worker = threading.Thread(target=second)
        worker.start()
        driver.capture_html()
        worker.join(timeout=5.0)
        assert overlap == [False], (
            "첫 호출이 끝나기 전 두 번째 호출이 같은 연결에 진입했다 — "
            "연결 단위 락 부재(결함 ⑩)"
        )


# ── 진입점 — 3단계 모드 / 채널별 드라이버 / 추출기 필수 배선 ────────────────

RUN_JD = {
    "position_name": "Tech PM",
    "keyword_groups": [["백엔드", "Backend"], ["PM"]],
    "requirements": {"min_years": 3},
    "or_keywords": ["백엔드", "Backend"],
    "and_keywords": ["Python"],
    "career_min": 3,
    "career_max": 10,
}


def _write_jd(tmp_path, jd=None) -> str:
    jd_path = tmp_path / "jd.json"
    jd_path.write_text(
        json.dumps(jd or RUN_JD, ensure_ascii=False), encoding="utf-8"
    )
    return str(jd_path)


def _empty_extractors():
    return {ch: (lambda pages: []) for ch in CHANNELS}


class TestEntrypointModes:
    def test_default_mode_is_plan_only_with_zero_cdp_connections(self, tmp_path):
        """기본 모드 = plan-only — CDP 연결 시도 0 을 증명한다."""
        factory_calls: list[str] = []

        def factory(ws_url: str):
            factory_calls.append(ws_url)
            raise AssertionError("plan-only 모드에서 CDP 연결을 시도했다")

        report_out = tmp_path / "report.json"
        code = run_mod.main(
            [_write_jd(tmp_path), "--report-out", str(report_out)],
            transport_factory=factory,
        )
        assert code == 0
        assert factory_calls == [], "기본 모드가 브라우저에 접속했다(진입점 결함)"
        report = json.loads(report_out.read_text(encoding="utf-8"))
        assert report["mode"] == "plan_only"
        assert report["cdp_connections"] == 0
        # 계획 산출물: RPS 플랜 단계 + 포털 디스크립터 검증 결과
        assert report["linkedin_stages"], "RPS 플랜 단계가 비어 있다"
        assert {d["channel"] for d in report["descriptors"]} == {
            "saramin",
            "jobkorea",
        }

    def test_browser_flag_runs_attached_dry_run(self, tmp_path):
        report_out = tmp_path / "report.json"
        code = run_mod.main(
            [
                _write_jd(tmp_path),
                "--browser",
                "--ws-url",
                "ws://injected-not-used",
                "--pages-out",
                str(tmp_path / "pages.jsonl"),
                "--report-out",
                str(report_out),
            ],
            transport_factory=lambda ws_url: FakeTransport(),
            extractors=_empty_extractors(),
        )
        assert code == 0
        report = json.loads(report_out.read_text(encoding="utf-8"))
        assert report["mode"] == "browser_dry_run"
        assert report["live"] is False

    def test_live_remains_fail_closed(self, tmp_path):
        with pytest.raises(SystemExit) as exc:
            run_mod.main(
                [_write_jd(tmp_path), "--live", "--ws-url", "ws://x"],
                transport_factory=lambda ws_url: FakeTransport(),
                extractors=_empty_extractors(),
            )
        assert exc.value.code not in (0, None)


class TestEntrypointPerChannelDrivers:
    def test_each_channel_gets_independent_transport(self, tmp_path):
        transports: list[FakeTransport] = []

        def factory(ws_url: str):
            t = FakeTransport()
            transports.append(t)
            return t

        code = run_mod.main(
            [
                _write_jd(tmp_path),
                "--browser",
                "--ws-url",
                "ws://x",
                "--pages-out",
                str(tmp_path / "pages.jsonl"),
                "--report-out",
                str(tmp_path / "report.json"),
            ],
            transport_factory=factory,
            extractors=_empty_extractors(),
        )
        assert code == 0
        assert len(transports) == 3, (
            "채널당 독립 드라이버(탭/연결)가 아니라 단일 연결 공유다(결함 ⑩)"
        )
        # 채널 명령이 각자의 트랜스포트로만 갔다 — 응답 혼선 없음.
        def navigated(t: FakeTransport) -> list[str]:
            return [p["url"] for m, p in t.calls if m == "Page.navigate"]

        saramin_ts = [
            t for t in transports if any("saramin" in u for u in navigated(t))
        ]
        jobkorea_ts = [
            t for t in transports if any("jobkorea" in u for u in navigated(t))
        ]
        assert len(saramin_ts) == 1 and len(jobkorea_ts) == 1
        assert saramin_ts[0] is not jobkorea_ts[0]
        assert not any("jobkorea" in u for u in navigated(saramin_ts[0]))
        assert not any("saramin" in u for u in navigated(jobkorea_ts[0]))


class TestExtractorWiring:
    def test_build_deps_requires_extractor(self):
        h = Harness(pages=1)
        with pytest.raises(TypeError):
            run_mod.build_deps(  # extract_candidates 누락 — silent 0 금지
                h.driver, h.store, h.monitor, h.recorder, "macmini"
            )

    def test_browser_mode_without_extractors_fails_explicitly(self, tmp_path):
        with pytest.raises(SystemExit) as exc:
            run_mod.main(
                [_write_jd(tmp_path), "--browser", "--ws-url", "ws://x"],
                transport_factory=lambda ws_url: FakeTransport(),
            )
        assert exc.value.code not in (0, None)

    def test_stored_html_flows_to_scoring_exclusion_and_registration(
        self, tmp_path
    ):
        """저장된 페이지 HTML → 후보 dict → 채점·제외·등록까지 배선 증명."""
        seen_pages: dict[str, list[dict]] = {}

        def saramin_extractor(pages: list[dict]) -> list[dict]:
            seen_pages["saramin"] = pages
            excluded_payload = _score_payload()
            excluded_payload["dimensions"]["D2"]["evidence"] = "스타트업 인턴"
            return [
                _candidate(PAYLOAD_60, "https://saramin.example/p/ok"),
                _candidate(excluded_payload, "https://saramin.example/p/intern"),
            ]

        extractors = _empty_extractors()
        extractors["saramin"] = saramin_extractor

        jd = dict(RUN_JD)
        jd["not_keywords"] = ["인턴"]
        report_out = tmp_path / "report.json"
        recorder = DualRecorder(FakeClickUp(), FakeDiscord())  # dry-run 기록기
        code = run_mod.main(
            [
                _write_jd(tmp_path, jd),
                "--browser",
                "--ws-url",
                "ws://x",
                "--pages-out",
                str(tmp_path / "pages.jsonl"),
                "--report-out",
                str(report_out),
            ],
            transport_factory=lambda ws_url: FakeTransport(),
            extractors=extractors,
            recorder=recorder,
        )
        assert code == 0
        # 추출기는 저장된 페이지 HTML(raw)을 실제로 받았다.
        assert seen_pages["saramin"], "저장된 페이지가 추출기로 전달되지 않았다"
        assert any(
            "<html>" in row.get("raw_html_or_text", "")
            for row in seen_pages["saramin"]
        )
        report = json.loads(report_out.read_text(encoding="utf-8"))
        assert len(report["registered"]) == 1  # 정상 후보는 등록 흐름 도달
        assert len(report["drafts"]) == 1
        assert len(report["excluded"]) == 1  # 제외어 후보는 excluded 처리
        assert report["excluded"][0]["matched_keyword"] == "인턴"
