"""V1 독립검증 결함5 — 30초 자동재개가 실제로 대기·재시도하는지 검증.

goal: docs/engineering/aisearch-fleet-next-steps-goal-2026-08-01.md (V1 finding #5)

기존 코드는 PAUSED_HUMAN 이면 waiting_resume 상태로 즉시 종료했다 —
InterventionMonitor.poll() 자체는 30초 무입력이면 스스로 RUNNING 으로
돌아가지만, 그걸 실제로 재확인하는 대기·재시도 루프가 run.py 에 없었다.
이 테스트는 run_mod.time.monotonic 을 페이크 시계로 바꾸고, injected
sleep 이 그 시계를 실제로 전진시키게 해 "대기 후 재확인"이 진짜로 일어나는지
결정론적으로 검증한다(실 time.sleep 0).
"""
from __future__ import annotations

import json

import pytest

from apps.aisearch import run as run_mod
from apps.aisearch.core.discord_notify import DiscordNotifier
from apps.aisearch.core.intervention import RESUME_DELAY_SECONDS

JD = {
    "position_name": "Tech PM",
    "keyword_groups": [["백엔드", "Backend"]],
    "requirements": {"min_years": 3},
    "or_keywords": ["백엔드"],
    "and_keywords": ["Python"],
    "career_min": 3,
    "career_max": 10,
}


def _write_jd(tmp_path) -> str:
    jd_path = tmp_path / "jd.json"
    jd_path.write_text(json.dumps(JD, ensure_ascii=False), encoding="utf-8")
    return str(jd_path)


class _OneShotHumanInputTransport:
    """1페이지 소진 + 첫 poll_events 호출에서만 사람 입력 신호 1건 발생."""

    def __init__(self) -> None:
        self.current = "https://fake.test/list"
        self._snapshot_calls = 0
        self._human_signal_sent = False

    def __call__(self, method: str, params: dict) -> dict:
        if method == "Page.navigate":
            self.current = params["url"]
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
            value = f"<html>{self.current}</html>"
        elif "/*vh:url*/" in expr:
            value = self.current
        elif "/*vh:detail_refs*/" in expr:
            value = []
        elif "/*vh:has_next*/" in expr:
            value = False
        elif "/*vh:snapshot*/" in expr:
            self._snapshot_calls += 1
            human_count = 1 if self._snapshot_calls >= 1 and not self._human_signal_sent else 0
            if human_count:
                self._human_signal_sent = True
            value = {
                "h": human_count,
                "present": True,
                "captcha": False,
                "cloudflare": False,
                "twofa": False,
                "checkpoint": False,
                "multisession": False,
            }
        return {"result": {"value": value}}


class TestAutoResumeLoop:
    def test_pipeline_auto_resumes_after_simulated_30s_idle(self, tmp_path, monkeypatch):
        fake_now = [0.0]
        monkeypatch.setattr(run_mod.time, "monotonic", lambda: fake_now[0])

        slept: list[float] = []

        def fake_sleep(seconds: float) -> None:
            slept.append(seconds)
            fake_now[0] += seconds  # 실제로 시간이 흐른 것처럼 시계를 전진

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
            transport_factory=lambda ws_url: _OneShotHumanInputTransport(),
            extractors={ch: (lambda pages: []) for ch in run_mod.CHANNELS},
            notifier=DiscordNotifier(send=sent.append, live=True),
            sleep=fake_sleep,
        )

        # 사람 입력 신호가 1회 있었지만, 재시도 루프가 대기(가짜 시계 전진)
        # 후 자동으로 재확인해 결국 완료돼야 한다 — waiting_resume 로 그냥
        # 끝나버리면 이 결함(#5)이 되돌아온 것이다.
        assert code == 0
        assert len(slept) >= 1  # 실제로 대기(재시도)가 있었다는 증거
        assert sum(slept) >= RESUME_DELAY_SECONDS - 1e-6  # 충분히 기다렸다

    def test_gives_up_after_max_attempts_if_never_clears(self, tmp_path, monkeypatch):
        """사람이 계속 만지고 있으면(=계속 idle=0) 무한 대기하지 않고 정직하게 waiting_resume 로 끝난다."""
        monkeypatch.setattr(run_mod.time, "monotonic", lambda: 0.0)  # 시계가 절대 안 흐름

        class _AlwaysHumanInputTransport(_OneShotHumanInputTransport):
            def __call__(self, method: str, params: dict) -> dict:
                result = super().__call__(method, params)
                expr = params.get("expression", "")
                if "/*vh:snapshot*/" in expr:
                    result["result"]["value"]["h"] = self._snapshot_calls  # 매번 계속 증가 = 계속 사람 입력
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

        assert code != 0  # completed 가 아님(waiting_resume 로 끝남) — 정직한 실패
        assert len(slept) == 3  # 재시도 상한을 지켰다(무한 대기 아님)
