"""V1 5차 적대검증 — 신규 BLOCKER 3건 RED 재현.

① cdp_driver: 상세 프로필을 현재 탭으로 연 뒤 목록으로 복귀하지 않아
   상세 화면에서 '다음 페이지'를 찾다 중단 → 2페이지 진행 불가.
② run.py JsonlPageStore: append 만 해서 재실행 시 중복 + 추출 시 채널만
   구분해 예전 실행의 다른 포지션 자료가 혼입.
③ 차단 알림이 stderr 출력뿐 — Discord 알림 계약(채널 1512503041448743092)
   위반. notifier 어댑터(주입식 send, --live 게이트) 미배선.

전부 실 네트워크/브라우저 접속 0 — 페이크 트랜스포트/페이크 send 만 사용.
"""
from __future__ import annotations

import json

import pytest

from apps.aisearch import run as run_mod
from apps.aisearch.core.cdp_driver import CdpDriver
from apps.aisearch.core.intervention import InterventionMonitor
from apps.aisearch.core.pagination_store import TABLE_NAME

LIST_URL = "https://fake.test/list?kw=backend"
DETAIL_URLS = (
    "https://fake.test/talent-pool/view/1",
    "https://fake.test/talent-pool/view/2",
)

SARAMIN_PAYLOAD = {
    "channel": "saramin",
    "url": LIST_URL,
    "steps": [
        {"order": 1, "kind": "text", "selector": "#kw", "values": ["백엔드"]}
    ],
}


class ListStateTransport:
    """URL 상태를 기억하는 페이크 트랜스포트 — '다음 페이지' 컨트롤은
    목록 화면에서만 존재한다(실 포털과 동일한 제약)."""

    def __init__(self) -> None:
        self.current = "about:blank"
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, method: str, params: dict) -> dict:
        self.calls.append((method, dict(params)))
        if method == "Page.navigate":
            self.current = params["url"]
            return {"frameId": "F1", "loaderId": "L1"}
        if method.startswith("Input."):
            return {}
        expr = params.get("expression", "")
        on_list = self.current == LIST_URL
        value: object = True
        if "/*vh:ready*/" in expr:
            value = "complete"
        elif "/*vh:url*/" in expr:
            value = self.current
        elif "/*vh:html*/" in expr:
            value = f"<html>{self.current}</html>"
        elif "/*vh:detail_refs*/" in expr:
            value = list(DETAIL_URLS) if on_list else []
        elif "/*vh:has_next*/" in expr:
            value = on_list
        elif "/*vh:next_page*/" in expr:
            # 상세 화면에는 목록의 '다음 페이지' 버튼이 없다.
            value = on_list
        elif "/*vh:snapshot*/" in expr:
            # V1 독립검증 결함1 재검증 이후: fetch_detail_page 도 poll_events 를
            # 부른다 — 차단신호 없는 정상 스냅샷 모양을 흉내낸다.
            value = {
                "h": 0,
                "present": True,
                "captcha": False,
                "cloudflare": False,
                "twofa": False,
                "checkpoint": False,
                "multisession": False,
            }
        return {"result": {"value": value}}


class TestBlocker1DetailThenNextPage:
    """① 상세 열람 후 목록 복귀 — 20페이지 순회가 이어져야 한다."""

    def _driver(self) -> tuple[CdpDriver, ListStateTransport]:
        transport = ListStateTransport()
        return CdpDriver(transport, sleep=lambda s: None), transport

    def test_detail_fetch_returns_to_list_url(self):
        driver, transport = self._driver()
        page1 = driver.fetch_list_page("saramin", 1, SARAMIN_PAYLOAD)
        assert page1["url"] == LIST_URL
        assert page1["detail_refs"] == list(DETAIL_URLS)

        for ref in DETAIL_URLS:
            detail = driver.fetch_detail_page("saramin", ref)
            assert detail["url"] == ref
            assert ref in detail["content"]  # 상세 원문은 상세 화면에서 캡처
            # 상세 열람 후에는 목록 화면으로 복귀해 있어야 한다(로드 대기 포함).
            assert transport.current == LIST_URL

    def test_page2_request_runs_against_list_context(self):
        driver, _ = self._driver()
        driver.fetch_list_page("saramin", 1, SARAMIN_PAYLOAD)
        for ref in DETAIL_URLS:
            driver.fetch_detail_page("saramin", ref)
        # 상세 2건 열람 후에도 2페이지 요청은 목록 화면 기준으로 실행돼야 한다.
        page2 = driver.fetch_list_page("saramin", 2, SARAMIN_PAYLOAD)
        assert page2["url"] == LIST_URL


class _DetailCaptchaTransport(ListStateTransport):
    """상세 화면(/talent-pool/view/1)에서만 캡차 스냅샷을 반환하는 페이크.

    실제 사고 재현: 목록 화면은 정상인데, 상세 프로필로 이동하는 순간 캡차가
    뜬다 — V1 독립검증 결함1(cdp_driver.py:595 구버전).
    """

    CAPTCHA_URL = DETAIL_URLS[0]

    def __call__(self, method: str, params: dict) -> dict:
        result = super().__call__(method, params)
        expr = params.get("expression", "")
        if "/*vh:snapshot*/" in expr and self.current == self.CAPTCHA_URL:
            result["result"]["value"] = {
                "h": 0,
                "present": True,
                "captcha": True,
                "cloudflare": False,
                "twofa": False,
                "checkpoint": False,
                "multisession": False,
            }
        return result


class TestDetailPageBlockDetection:
    """V1 독립검증 결함1 — 상세페이지 자체의 차단신호는 캡처 전에 잡혀야 한다."""

    def _driver(self):
        transport = _DetailCaptchaTransport()
        return CdpDriver(transport, sleep=lambda s: None), transport

    def test_captcha_on_detail_page_raises_before_capture_not_saved_as_content(self):
        from apps.aisearch.core.cdp_driver import DetailPageBlocked

        driver, transport = self._driver()
        driver.fetch_list_page("saramin", 1, SARAMIN_PAYLOAD)

        with pytest.raises(DetailPageBlocked) as excinfo:
            driver.fetch_detail_page("saramin", _DetailCaptchaTransport.CAPTCHA_URL)

        assert any(e.get("kind") == "captcha" for e in excinfo.value.events)
        # 차단 후에는 목록 화면으로 복귀해 있어야 한다(다음 페이지 순회 지속 가능).
        assert transport.current == LIST_URL

    def test_full_pipeline_blocks_on_detail_page_captcha_list_page_stays_clean(
        self, tmp_path
    ):
        """전체 파이프라인(run_mod.main) 통합 검증 — 목록은 정상, 상세에서만 캡차.

        기존 test_run_wires_notifier_into_blocked_flow 는 모든 페이지에 캡차를
        발생시켜(EntryFakeTransport 가 페이지 구분 없이 captcha 고정) 실제로는
        목록 페이지 차단 경로만 검증했다 — 상세페이지 전용 차단은 이 테스트가
        처음 커버한다(V1 독립검증 결함1 회귀 방지).
        """
        from apps.aisearch.core.discord_notify import DiscordNotifier

        class DetailOnlyCaptchaTransport:
            DETAIL_URL = "https://fake.test/talent-pool/view/1"

            def __init__(self) -> None:
                self.current = "https://fake.test/list"

            def __call__(self, method: str, params: dict) -> dict:
                if method == "Page.navigate":
                    self.current = params["url"]
                    return {"frameId": "F1", "loaderId": "L1"}
                if method.startswith("Input."):
                    return {}
                expr = params.get("expression", "")
                on_detail = self.current == self.DETAIL_URL
                value: object = True
                if "/*vh:ready*/" in expr:
                    value = "complete"
                elif "/*vh:count*/" in expr:
                    value = "12명"  # 링크드인은 정상 — 이 테스트의 관심사는 상세 캡차다
                elif "/*vh:rect*/" in expr:
                    value = {"x": 10.0, "y": 10.0}
                elif "/*vh:checked*/" in expr:
                    value = True
                elif "/*vh:html*/" in expr:
                    value = f"<html>{self.current}</html>"
                elif "/*vh:url*/" in expr:
                    value = self.current
                elif "/*vh:detail_refs*/" in expr:
                    value = [] if on_detail else [self.DETAIL_URL]
                elif "/*vh:has_next*/" in expr:
                    value = False
                elif "/*vh:snapshot*/" in expr:
                    value = {
                        "h": 0,
                        "present": True,
                        "captcha": on_detail,  # 목록은 정상, 상세만 캡차
                        "cloudflare": False,
                        "twofa": False,
                        "checkpoint": False,
                        "multisession": False,
                    }
                return {"result": {"value": value}}

        sent: list[dict] = []
        code = run_mod.main(
            [
                _write_jd(tmp_path),
                "--browser",
                "--ws-url",
                "ws://injected-not-used",
                "--pages-out",
                str(tmp_path / "pages.jsonl"),
            ],
            transport_factory=lambda ws_url: DetailOnlyCaptchaTransport(),
            extractors={ch: (lambda pages: []) for ch in run_mod.CHANNELS},
            notifier=DiscordNotifier(send=sent.append, live=True),
        )

        assert code == 1  # 상세페이지 캡차 → 파이프라인 전체가 완료 아님
        assert any("captcha" in s["content"] for s in sent)  # 차단 알림 실제 감지
        # 상세페이지 원문("view/1")이 후보 데이터로 저장되지 않았는지 확인.
        pages_content = (tmp_path / "pages.jsonl").read_text(encoding="utf-8")
        assert "view/1" not in pages_content


def _page_row(position_ref: str, url: str, raw: str) -> dict:
    return {
        "id": f"{position_ref}|{url}",
        "channel": "saramin",
        "page_type": "list",
        "url": url,
        "captured_at": "2026-07-31T00:00:00+00:00",
        "raw_html_or_text": raw,
        "position_ref": position_ref,
        "machine": "macmini",
    }


class TestBlocker2StoreUpsertAndPositionFilter:
    """② 저장 키(channel+position_ref+url) upsert + 현재 포지션 필터."""

    def test_same_key_upserts_without_duplicates(self, tmp_path):
        path = tmp_path / "pages.jsonl"
        store = run_mod.JsonlPageStore(path)
        store.upsert(TABLE_NAME, _page_row("Tech PM", LIST_URL, "v1"))
        store.upsert(TABLE_NAME, _page_row("Tech PM", LIST_URL, "v2"))
        lines = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
        ]
        assert len(lines) == 1  # 같은 실행 내 재시도 → 중복 0
        assert lines[0]["raw_html_or_text"] == "v2"  # 기존 행 갱신

    def test_rerun_with_fresh_store_still_no_duplicates(self, tmp_path):
        path = tmp_path / "pages.jsonl"
        run_mod.JsonlPageStore(path).upsert(
            TABLE_NAME, _page_row("Tech PM", LIST_URL, "run1")
        )
        # 같은 실행을 한 번 더(새 프로세스 = 새 스토어 인스턴스) 돌린 상황.
        rerun_store = run_mod.JsonlPageStore(path)
        rerun_store.upsert(TABLE_NAME, _page_row("Tech PM", LIST_URL, "run2"))
        lines = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
        ]
        assert len(lines) == 1
        assert lines[0]["raw_html_or_text"] == "run2"

    def test_rows_for_filters_by_current_position_ref(self, tmp_path):
        store = run_mod.JsonlPageStore(tmp_path / "pages.jsonl")
        store.upsert(TABLE_NAME, _page_row("Old Position", "https://o/1", "old"))
        store.upsert(TABLE_NAME, _page_row("Tech PM", "https://n/1", "new"))
        rows = store.rows_for("saramin", "Tech PM")
        assert [r["raw_html_or_text"] for r in rows] == ["new"]


JD = {
    "position_name": "Tech PM",
    "keyword_groups": [["백엔드", "Backend"], ["PM"]],
    "requirements": {"min_years": 3},
    "or_keywords": ["백엔드", "Backend"],
    "and_keywords": ["Python"],
    "career_min": 3,
    "career_max": 10,
}


class EntryFakeTransport:
    """run.py 조립용 페이크 — 캡차 여부를 주입해 차단 흐름을 재현한다."""

    def __init__(self, captcha: bool = False) -> None:
        self.captcha = captcha

    def __call__(self, method: str, params: dict) -> dict:
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
            value = {
                "h": 0,
                "present": True,
                "captcha": self.captcha,
                "cloudflare": False,
                "twofa": False,
                "checkpoint": False,
                "multisession": False,
            }
        return {"result": {"value": value}}


def _write_jd(tmp_path) -> str:
    jd_path = tmp_path / "jd.json"
    jd_path.write_text(json.dumps(JD, ensure_ascii=False), encoding="utf-8")
    return str(jd_path)


class TestBlocker3DiscordBlockNotifier:
    """③ 차단 시 Discord notifier 계약 — 채널 ID·사유 payload, --live 게이트."""

    CHANNEL_ID = "1512503041448743092"

    def test_blocked_signal_sends_one_discord_payload(self):
        from apps.aisearch.core.discord_notify import DiscordNotifier

        sent: list[dict] = []
        notifier = DiscordNotifier(send=sent.append, live=True)
        monitor = InterventionMonitor(lambda: 0.0, notifier)
        monitor.on_signal("captcha")
        assert len(sent) == 1  # notifier 호출 1 — 실 네트워크 0(페이크 send)
        payload = sent[0]
        assert payload["channel_id"] == self.CHANNEL_ID
        assert "captcha" in payload["content"]  # 사유 포함

    def test_default_records_plan_only_without_sending(self):
        from apps.aisearch.core.discord_notify import DiscordNotifier

        sent: list[dict] = []
        notifier = DiscordNotifier(send=sent.append)  # 기본 = live 아님
        notifier.notify("차단 신호 감지(2fa)")
        assert sent == []  # 실제 발신은 --live 게이트 뒤에서만
        assert len(notifier.planned) == 1  # 기본은 발신 계획만 기록
        assert notifier.planned[0]["channel_id"] == self.CHANNEL_ID
        assert "2fa" in notifier.planned[0]["content"]

    def test_live_without_send_client_is_fail_closed(self):
        from apps.aisearch.core.discord_notify import (
            DiscordNotifier,
            DiscordNotifyError,
        )

        with pytest.raises(DiscordNotifyError):
            DiscordNotifier(send=None, live=True)

    def test_run_wires_notifier_into_blocked_flow(self, tmp_path):
        from apps.aisearch.core.discord_notify import DiscordNotifier

        sent: list[dict] = []
        code = run_mod.main(
            [
                _write_jd(tmp_path),
                "--browser",
                "--ws-url",
                "ws://injected-not-used",
                "--pages-out",
                str(tmp_path / "pages.jsonl"),
            ],
            transport_factory=lambda ws_url: EntryFakeTransport(captcha=True),
            extractors={ch: (lambda pages: []) for ch in run_mod.CHANNELS},
            notifier=DiscordNotifier(send=sent.append, live=True),
        )
        assert code == 1  # 차단 → completed 아님
        assert len(sent) == 1  # 차단 1건 → notifier 호출 1
        assert sent[0]["channel_id"] == self.CHANNEL_ID
        assert "captcha" in sent[0]["content"]
