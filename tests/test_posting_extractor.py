from __future__ import annotations

import unittest

from tools.multi_position_sourcing.posting_extractor import (
    collect_image_urls,
    extract_company_role_jd,
    extract_posting,
    has_sufficient_jd_text,
    jd_signal_count,
    needs_render_fallback,
)
from tools.multi_position_sourcing.posting_models import ExtractedPosting, FetchResult


WANTED_HTML = """<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta property="og:site_name" content="밸류커넥트">
  <meta property="og:title" content="시니어 백엔드 엔지니어">
  <meta property="og:image" content="https://static.wanted.co.kr/og/cover.png">
  <title>채용 - 시니어 백엔드 엔지니어</title>
</head>
<body>
  <section>
    <h2>회사소개</h2>
    <p>밸류커넥트는 채용 매칭 플랫폼을 운영하는 HR 테크 회사입니다.</p>
    <h2>주요업무</h2>
    <ul>
      <li>대규모 트래픽을 처리하는 백엔드 API 설계 및 개발</li>
      <li>매칭 파이프라인 성능 최적화</li>
    </ul>
    <h2>자격요건</h2>
    <ul>
      <li>5년 이상 백엔드 개발 경력</li>
      <li>Python 또는 Go 실무 경험</li>
    </ul>
    <h2>우대사항</h2>
    <ul>
      <li>대규모 분산 시스템 경험</li>
    </ul>
    <img src="/images/team-photo.jpg" alt="team">
    <img src="https://cdn.wanted.co.kr/images/office.png" alt="office">
    <img src="data:image/png;base64,AAAA" alt="inline">
    <img src="/images/team-photo.jpg" alt="dup">
  </section>
</body>
</html>"""

THIN_HTML = "<html><head><title>loading</title></head><body><div id=\"app\"></div></body></html>"


class FakeFetcher:
    """Records calls and returns a queued FetchResult per invocation."""

    def __init__(self, *results: FetchResult) -> None:
        self._results = list(results)
        self.calls: list[str] = []

    def __call__(self, url: str) -> FetchResult:
        self.calls.append(url)
        if len(self._results) == 1:
            return self._results[0]
        return self._results[len(self.calls) - 1]


class FakeImageDownloader:
    """Records (urls, dir) and returns deterministic fake evidence paths."""

    def __init__(self) -> None:
        self.calls: list[tuple[tuple[str, ...], str]] = []

    def __call__(self, urls: tuple[str, ...], out_dir: str) -> tuple[str, ...]:
        self.calls.append((urls, out_dir))
        return tuple(f"{out_dir}/img_{i}.png" for i in range(len(urls)))


class ExtractCompanyRoleJdTests(unittest.TestCase):
    def test_parses_wanted_style_html(self) -> None:
        company, role, jd_text = extract_company_role_jd(WANTED_HTML)
        self.assertEqual(company, "밸류커넥트")
        self.assertEqual(role, "시니어 백엔드 엔지니어")
        self.assertIn("주요업무", jd_text)
        self.assertIn("자격요건", jd_text)
        self.assertIn("우대사항", jd_text)
        self.assertIn("회사소개", jd_text)
        self.assertIn("백엔드 API 설계", jd_text)


class CollectImageUrlsTests(unittest.TestCase):
    def test_resolves_dedupes_and_skips_data_uris(self) -> None:
        urls = collect_image_urls(WANTED_HTML, "https://www.wanted.co.kr/wd/12345")
        self.assertIn("https://www.wanted.co.kr/images/team-photo.jpg", urls)
        self.assertIn("https://cdn.wanted.co.kr/images/office.png", urls)
        self.assertIn("https://static.wanted.co.kr/og/cover.png", urls)
        # data: URI is skipped
        self.assertFalse(any(u.startswith("data:") for u in urls))
        # relative duplicate is collapsed
        self.assertEqual(
            sum(1 for u in urls if u == "https://www.wanted.co.kr/images/team-photo.jpg"),
            1,
        )


class JdSignalTests(unittest.TestCase):
    def test_signal_count_rich_vs_thin(self) -> None:
        rich = "주요업무 담당업무 자격요건 우대사항"
        self.assertGreaterEqual(jd_signal_count(rich), 4)
        self.assertEqual(jd_signal_count("안녕하세요 점심 메뉴 추천"), 0)

    def test_has_sufficient_jd_text(self) -> None:
        rich = (
            "주요업무: 백엔드 API 설계 및 개발. 자격요건: 5년 이상 경력. "
            "우대사항: 분산 시스템 경험. 회사소개: HR 테크 회사입니다. " * 2
        )
        self.assertTrue(has_sufficient_jd_text(rich))
        self.assertFalse(has_sufficient_jd_text("점심 뭐 먹지"))
        # signal-rich but too short fails the length gate
        self.assertFalse(has_sufficient_jd_text("주요업무 자격요건"))


class NeedsRenderFallbackTests(unittest.TestCase):
    def test_true_when_empty_or_thin(self) -> None:
        empty = FetchResult(url="u", ok=True, status_code=200, html="", fetch_method="httpx")
        self.assertTrue(needs_render_fallback(empty, ""))
        thin = FetchResult(url="u", ok=True, status_code=200, html=THIN_HTML, fetch_method="httpx")
        self.assertTrue(needs_render_fallback(thin, "주요업무"))
        blocked = FetchResult(url="u", ok=False, status_code=403, fetch_method="httpx", reason="blocked")
        self.assertTrue(needs_render_fallback(blocked, ""))

    def test_false_when_rich(self) -> None:
        rich_jd = (
            "주요업무: 백엔드 API 설계 및 개발. 자격요건: 5년 이상 경력. "
            "우대사항: 분산 시스템 경험. 회사소개: HR 테크 회사입니다. " * 2
        )
        ok = FetchResult(url="u", ok=True, status_code=200, html="<html>...</html>", fetch_method="httpx")
        self.assertFalse(needs_render_fallback(ok, rich_jd))


class ExtractPostingTests(unittest.TestCase):
    def test_httpx_path_returns_ok_posting(self) -> None:
        http_fetch = FakeFetcher(
            FetchResult(url="https://www.wanted.co.kr/wd/12345", ok=True, status_code=200, html=WANTED_HTML, fetch_method="httpx")
        )
        downloader = FakeImageDownloader()
        result = extract_posting(
            "https://www.wanted.co.kr/wd/12345",
            http_fetch=http_fetch,
            render_fetch=None,
            image_downloader=downloader,
            artifacts_dir="artifacts/test_pos",
        )
        self.assertIsInstance(result, ExtractedPosting)
        self.assertTrue(result.ok)
        self.assertEqual(result.fetch_method, "httpx")
        self.assertEqual(result.company, "밸류커넥트")
        self.assertEqual(result.role, "시니어 백엔드 엔지니어")
        self.assertIn("주요업무", result.jd_text)
        # render fetch must not be consulted on the happy httpx path
        self.assertEqual(http_fetch.calls, ["https://www.wanted.co.kr/wd/12345"])

    def test_fallback_to_playwright_when_httpx_thin(self) -> None:
        http_fetch = FakeFetcher(
            FetchResult(url="https://www.wanted.co.kr/wd/12345", ok=True, status_code=200, html=THIN_HTML, fetch_method="httpx")
        )
        render_fetch = FakeFetcher(
            FetchResult(url="https://www.wanted.co.kr/wd/12345", ok=True, status_code=200, html=WANTED_HTML, fetch_method="playwright")
        )
        result = extract_posting(
            "https://www.wanted.co.kr/wd/12345",
            http_fetch=http_fetch,
            render_fetch=render_fetch,
            image_downloader=None,
            artifacts_dir="artifacts/test_pos",
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.fetch_method, "playwright")
        self.assertEqual(result.company, "밸류커넥트")
        self.assertEqual(result.role, "시니어 백엔드 엔지니어")
        self.assertEqual(len(render_fetch.calls), 1)

    def test_fail_closed_when_both_blocked(self) -> None:
        http_fetch = FakeFetcher(
            FetchResult(url="u", ok=False, status_code=403, html="", fetch_method="httpx", reason="blocked")
        )
        render_fetch = FakeFetcher(
            FetchResult(url="u", ok=False, status_code=0, html="", fetch_method="playwright", reason="timeout")
        )
        result = extract_posting(
            "https://www.wanted.co.kr/wd/99999",
            http_fetch=http_fetch,
            render_fetch=render_fetch,
            image_downloader=None,
            artifacts_dir="artifacts/test_pos",
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.company, "")
        self.assertEqual(result.role, "")
        self.assertTrue(result.reason)

    def test_image_downloader_records_and_populates_evidence(self) -> None:
        http_fetch = FakeFetcher(
            FetchResult(url="https://www.wanted.co.kr/wd/12345", ok=True, status_code=200, html=WANTED_HTML, fetch_method="httpx")
        )
        downloader = FakeImageDownloader()
        result = extract_posting(
            "https://www.wanted.co.kr/wd/12345",
            http_fetch=http_fetch,
            render_fetch=None,
            image_downloader=downloader,
            artifacts_dir="artifacts/test_pos",
        )
        self.assertEqual(len(downloader.calls), 1)
        recorded_urls, recorded_dir = downloader.calls[0]
        self.assertIn("https://www.wanted.co.kr/images/team-photo.jpg", recorded_urls)
        self.assertEqual(recorded_dir, "artifacts/test_pos")
        self.assertTrue(result.image_evidence_paths)
        self.assertEqual(len(result.image_evidence_paths), len(recorded_urls))


if __name__ == "__main__":
    unittest.main()
