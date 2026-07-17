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

from tools.multi_position_sourcing.session_guard import (
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

    def test_not_due_skips(self) -> None:
        action = decide_keepalive("saramin", due=False, owner_active=False, cookie_evidence="present")
        self.assertEqual(action, "skip_not_due")

    def test_cookie_present_never_opens_page(self) -> None:
        action = decide_keepalive("jobkorea", due=True, owner_active=False, cookie_evidence="present")
        self.assertEqual(action, "cookie_only_ok")

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


class ProbeUrlTests(unittest.TestCase):
    def test_jobkorea_probe_url_uses_uppercase_corp_person_find(self) -> None:
        self.assertEqual(PROBE_URLS["jobkorea"], "https://www.jobkorea.co.kr/Corp/Person/Find")

    def test_probe_urls_are_readonly_surfaces(self) -> None:
        for site, url in PROBE_URLS.items():
            self.assertTrue(url.startswith("https://"), site)


class SnapshotRollingTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
