"""세션가드 코어 — SOT-28 §4(세션 상시 유지)·§3a(사람게이트)·§5(LinkedIn 단일기기) 순수 판정.

직전 세션의 session_guard/vault/cdp_util 아이디어(쿠키 스냅샷 롤링·2단계 판정·LinkedIn
자동로그인 금지)를 새 scripts/ 트리가 아니라 v5 기존 인프라(raw_cdp·owner_activity·
portal_keychain) 위에 재작성한다(2026-07-17 /st 지시 5).

인수 기준(기계 단언):
- keepalive 주기: 사람인·잡코리아 900초(≤15분, 서버세션 20~30분 만료보다 짧게),
  LinkedIn 1800초 읽기 전용 (SOT-28 §4).
- keepalive 직전 사람 점유 확인이 **최우선** — owner_active 면 due 여도 그 회차 건너뜀.
- 2단계 판정: 1단계 쿠키 증거 present → 페이지 열지 않음(cookie_only_ok).
  unknown → 읽기 전용 probe 1회. absent → 사람인/잡코리아 = 자동 재로그인(reauth),
  LinkedIn = human_wait (자동 폼 로그인 금지, §3a 라이선스 리스크).
- 잡코리아 probe URL 은 대문자 /Corp/Person/Find.
- 쿠키 스냅샷 롤링: site 별 최신 N개 유지, 파일 권한 0600(비밀값 — 로그 금지).
"""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from tools.multi_position_sourcing.session_guard import (
    run_keepalive_once,
    KEEPALIVE_INTERVAL_SECONDS,
    PROBE_URLS,
    SESSION_COOKIE_NAMES,
    classify_cookie_evidence,
    decide_keepalive,
    keepalive_due,
    save_cookie_snapshot,
)


class KeepaliveIntervalTests(unittest.TestCase):
    def test_intervals_follow_sot28(self) -> None:
        self.assertLessEqual(KEEPALIVE_INTERVAL_SECONDS["saramin"], 900)
        self.assertLessEqual(KEEPALIVE_INTERVAL_SECONDS["jobkorea"], 900)
        self.assertEqual(KEEPALIVE_INTERVAL_SECONDS["linkedin_rps"], 1800)

    def test_due_only_after_interval(self) -> None:
        self.assertFalse(keepalive_due("saramin", last_at=1000.0, now=1000.0 + 899))
        self.assertTrue(keepalive_due("saramin", last_at=1000.0, now=1000.0 + 900))
        self.assertTrue(keepalive_due("saramin", last_at=None, now=42.0))  # 첫 회차는 due


class DecideKeepaliveTests(unittest.TestCase):
    def test_owner_active_skips_even_when_due(self) -> None:
        # SOT-28 §4: keepalive 직전마다 사람 점유를 새로 확인, 사용 중이면 건너뜀.
        action = decide_keepalive("saramin", due=True, owner_active=True, cookie_evidence="present")
        self.assertEqual(action, "skip_owner_active")

    def test_owner_active_label_wins_even_when_also_not_due(self) -> None:
        # 판정 우선순위 봉인(뮤턴트 검사에서 발견된 미봉인 경계): 사람 점유가
        # 항상 1순위 — not_due 와 겹쳐도 skip_owner_active 로 보고해야
        # 운영 로그에서 "사장님 사용 중" 신호가 묻히지 않는다.
        action = decide_keepalive("saramin", due=False, owner_active=True, cookie_evidence="unknown")
        self.assertEqual(action, "skip_owner_active")

    def test_not_due_skips(self) -> None:
        action = decide_keepalive("saramin", due=False, owner_active=False, cookie_evidence="present")
        self.assertEqual(action, "skip_not_due")

    def test_cookie_present_is_only_diagnostic_and_still_requires_real_probe(self) -> None:
        action = decide_keepalive("jobkorea", due=True, owner_active=False, cookie_evidence="present")
        self.assertEqual(action, "probe_readonly")

    def test_cookie_unknown_probes_readonly_once(self) -> None:
        action = decide_keepalive("jobkorea", due=True, owner_active=False, cookie_evidence="unknown")
        self.assertEqual(action, "probe_readonly")

    def test_cookie_absent_reauth_for_saramin_jobkorea(self) -> None:
        for site in ("saramin", "jobkorea"):
            action = decide_keepalive(site, due=True, owner_active=False, cookie_evidence="absent")
            self.assertEqual(action, "reauth", site)

    def test_linkedin_absent_is_human_wait_never_auto_login(self) -> None:
        # SOT-28 §3a/§5: LinkedIn 은 자동 폼 로그인 금지 + 계정당 단일 기기.
        action = decide_keepalive("linkedin_rps", due=True, owner_active=False, cookie_evidence="absent")
        self.assertEqual(action, "human_wait")


class CookieEvidenceTests(unittest.TestCase):
    def test_session_cookie_names(self) -> None:
        self.assertIn("JSESSIONID", SESSION_COOKIE_NAMES["saramin"])
        self.assertIn("ASP.NET_SessionId", SESSION_COOKIE_NAMES["jobkorea"])
        self.assertIn("li_at", SESSION_COOKIE_NAMES["linkedin_rps"])

    def test_classify(self) -> None:
        cookies = [{"name": "li_at", "value": "x", "domain": ".linkedin.com"}]
        self.assertEqual(classify_cookie_evidence("linkedin_rps", cookies), "present")
        self.assertEqual(classify_cookie_evidence("saramin", cookies), "absent")
        self.assertEqual(classify_cookie_evidence("saramin", None), "unknown")

    def test_unrelated_domain_cookie_never_proves_session(self) -> None:
        cookies = [{"name": "JSESSIONID", "value": "secret", "domain": ".evil.example"}]
        self.assertEqual(classify_cookie_evidence("saramin", cookies), "absent")


class ProbeUrlTests(unittest.TestCase):
    def test_jobkorea_probe_url_uses_uppercase_corp_person_find(self) -> None:
        self.assertEqual(PROBE_URLS["jobkorea"], "https://www.jobkorea.co.kr/Corp/Person/Find")

    def test_probe_urls_are_readonly_surfaces(self) -> None:
        for site, url in PROBE_URLS.items():
            self.assertTrue(url.startswith("https://"), site)


class SnapshotRollingTests(unittest.TestCase):
    def test_existing_file_with_loose_permissions_is_forced_back_to_0600(self) -> None:
        # V1 적대검증 반례(2026-07-18): O_CREAT|O_TRUNC 는 기존 파일의 권한을
        # 유지한다 — 같은 타임스탬프 경로가 0644 로 선존재하면 비밀 쿠키가
        # 0644 파일에 남았다. 저장 후 무조건 0600 강제를 봉인한다.
        cookies = [{"name": "JSESSIONID", "value": "secret", "domain": ".saramin.co.kr"}]
        with TemporaryDirectory(prefix="sg_perm_") as root:
            expected = save_cookie_snapshot("saramin", cookies, root=Path(root), now=1000.0)
            os.chmod(expected, 0o644)  # 권한이 느슨해진 선존재 파일 재현
            again = save_cookie_snapshot("saramin", cookies, root=Path(root), now=1000.0)
            self.assertEqual(expected, again)
            self.assertEqual(oct(again.stat().st_mode & 0o777), oct(0o600))


    def test_snapshot_rolls_and_keeps_latest_n_with_0600(self) -> None:
        cookies = [{"name": "JSESSIONID", "value": "secret", "domain": ".saramin.co.kr"}]
        with TemporaryDirectory(prefix="sg_snap_") as root:
            paths = []
            for i in range(7):
                p = save_cookie_snapshot("saramin", cookies, root=Path(root), keep=5,
                                         now=1000.0 + i)
                paths.append(p)
            remaining = sorted(Path(root).glob("saramin-*.json"))
            self.assertEqual(len(remaining), 5, "최신 5개만 유지(롤링)")
            newest = max(remaining, key=lambda p: p.stat().st_mtime)
            self.assertEqual(oct(newest.stat().st_mode & 0o777), oct(0o600))
            data = json.loads(newest.read_text())
            self.assertEqual(data["site"], "saramin")
            self.assertEqual(data["cookies"][0]["name"], "JSESSIONID")
            self.assertNotIn("value", data["cookies"][0], "plaintext cookie secret must never persist")


class RunKeepaliveOnceTests(unittest.TestCase):
    def test_owner_check_happens_before_any_browser_touch(self) -> None:
        touched = []
        result = run_keepalive_once(
            "saramin",
            owner_snapshot=lambda: SimpleNamespace(owner_activity_detected=True),
            tab_factory=lambda: touched.append("attach"),
            last_at=None, now=100.0,
        )
        self.assertEqual(result["action"], "skip_owner_active")
        self.assertEqual(touched, [], "사장님 사용 중엔 CDP attach 자체를 하면 안 된다")

    def test_cookie_present_never_counts_as_keepalive_success_or_persists_secret(self) -> None:
        class FakeTab:
            def __init__(self) -> None:
                self.closed = 0

            def send(self, method: str, params: dict | None = None) -> dict:
                return {"cookies": [{"name": "JSESSIONID", "value": "s", "domain": ".saramin.co.kr"}]}

            def close(self) -> None:
                self.closed += 1

        tab = FakeTab()
        with TemporaryDirectory(prefix="sg_run_") as root:
            result = run_keepalive_once(
                "saramin",
                owner_snapshot=lambda: SimpleNamespace(owner_activity_detected=False),
                tab_factory=lambda: tab,
                last_at=None, now=100.0, snapshot_root=Path(root),
            )
            self.assertEqual(result["action"], "probe_readonly")
            self.assertEqual(len(list(Path(root).glob("saramin-*.json"))), 1)
            stored = json.loads(next(Path(root).glob("saramin-*.json")).read_text())
            self.assertNotIn("value", stored["cookies"][0])
        self.assertEqual(tab.closed, 1, "종료 = WebSocket 해제(close) 1회만")

    def test_cookie_fetch_failure_falls_back_to_probe_action(self) -> None:
        class BrokenTab:
            def send(self, method: str, params: dict | None = None) -> dict:
                raise RuntimeError("cdp unavailable")

            def close(self) -> None:
                pass

        result = run_keepalive_once(
            "jobkorea",
            owner_snapshot=lambda: SimpleNamespace(owner_activity_detected=False),
            tab_factory=lambda: BrokenTab(),
            last_at=None, now=100.0,
        )
        self.assertEqual(result["action"], "probe_readonly")
        self.assertEqual(result["cookie_evidence"], "unknown")
