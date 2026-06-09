from __future__ import annotations

from html.parser import HTMLParser
from typing import Callable
from urllib.parse import urljoin, urlsplit, urlunsplit

from tools.multi_position_sourcing.posting_models import ExtractedPosting, FetchResult


# JD signal vocabulary (Korean + English) reused across the recognition layer.
JD_SIGNALS: tuple[str, ...] = (
    "담당업무",
    "자격요건",
    "우대사항",
    "주요업무",
    "채용",
    "포지션",
    "JD",
    "회사소개",
    "responsibilities",
    "requirements",
    "qualifications",
)

# Headings used to scope the JD body text extraction.
JD_HEADINGS: tuple[str, ...] = ("주요업무", "담당업무", "자격요건", "우대사항", "회사소개")


def jd_signal_count(text: str) -> int:
    """Count how many distinct JD signals are present in ``text`` (case-insensitive)."""
    if not text:
        return 0
    lowered = text.lower()
    return sum(1 for signal in JD_SIGNALS if signal.lower() in lowered)


def has_sufficient_jd_text(text: str, *, min_signals: int = 2, min_length: int = 120) -> bool:
    """Return True when ``text`` is long enough and carries enough JD signals."""
    if not text:
        return False
    return len(text.strip()) >= min_length and jd_signal_count(text) >= min_signals


class _PostingHTMLParser(HTMLParser):
    """Stdlib HTML parser collecting OG metadata, JSON-LD, image srcs and visible text."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.og: dict[str, str] = {}
        self.title: str = ""
        self.img_srcs: list[str] = []
        self.json_ld_chunks: list[str] = []
        self._text_parts: list[str] = []
        self._capture_title = False
        self._capture_jsonld = False
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {k: (v or "") for k, v in attrs}
        if tag == "meta":
            prop = (attr.get("property") or attr.get("name") or "").lower()
            content = attr.get("content", "")
            if prop.startswith("og:") and content:
                self.og[prop] = content
        elif tag == "title":
            self._capture_title = True
        elif tag == "img":
            src = attr.get("src", "").strip()
            if src:
                self.img_srcs.append(src)
        elif tag == "script":
            if (attr.get("type") or "").lower() == "application/ld+json":
                self._capture_jsonld = True
        elif tag in ("style", "noscript"):
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._capture_title = False
        elif tag == "script":
            self._capture_jsonld = False
        elif tag in ("style", "noscript") and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._capture_jsonld:
            self.json_ld_chunks.append(data)
            return
        if self._capture_title:
            self.title += data
            return
        if self._skip_depth:
            return
        stripped = data.strip()
        if stripped:
            self._text_parts.append(stripped)

    def visible_text(self) -> str:
        return "\n".join(self._text_parts)


def _parse_html(html: str) -> _PostingHTMLParser:
    parser = _PostingHTMLParser()
    try:
        parser.feed(html)
    except Exception:
        # Malformed markup must never raise out of extraction (fail-closed).
        pass
    return parser


def _company_role_from_jsonld(chunks: list[str]) -> tuple[str, str]:
    """Best-effort JobPosting company/role from JSON-LD, stdlib json only."""
    import json

    for chunk in chunks:
        text = chunk.strip()
        if not text:
            continue
        try:
            data = json.loads(text)
        except Exception:
            continue
        candidates = data if isinstance(data, list) else [data]
        for entry in candidates:
            if not isinstance(entry, dict):
                continue
            entry_type = entry.get("@type", "")
            types = entry_type if isinstance(entry_type, list) else [entry_type]
            if "JobPosting" not in types:
                continue
            role = str(entry.get("title", "") or "").strip()
            org = entry.get("hiringOrganization", "")
            if isinstance(org, dict):
                company = str(org.get("name", "") or "").strip()
            else:
                company = str(org or "").strip()
            if company or role:
                return company, role
    return "", ""


def extract_company_role_jd(html: str) -> tuple[str, str, str]:
    """Extract ``(company, role, jd_text)`` from posting HTML using stdlib parsing.

    Precedence: og:site_name/og:title and JSON-LD ``JobPosting`` for company/role;
    the visible text (scoped around 주요업무/담당업무/자격요건/우대사항/회사소개 headings) for jd_text.
    """
    if not html:
        return "", "", ""

    parser = _parse_html(html)

    company = parser.og.get("og:site_name", "").strip()
    role = parser.og.get("og:title", "").strip()

    if not company or not role:
        ld_company, ld_role = _company_role_from_jsonld(parser.json_ld_chunks)
        company = company or ld_company
        role = role or ld_role

    if not role and parser.title:
        role = parser.title.strip()

    jd_text = parser.visible_text().strip()
    return company, role, jd_text


def collect_image_urls(html: str, base_url: str) -> tuple[str, ...]:
    """Return absolute, deduped image URLs from ``<img src>`` and ``og:image``.

    Relative URLs are resolved against ``base_url``; ``data:`` URIs are skipped;
    insertion order is preserved.
    """
    if not html:
        return ()

    parser = _parse_html(html)

    raw: list[str] = list(parser.img_srcs)
    og_image = parser.og.get("og:image", "").strip()
    if og_image:
        raw.append(og_image)

    resolved: list[str] = []
    seen: set[str] = set()
    for src in raw:
        candidate = src.strip()
        if not candidate or candidate.lower().startswith("data:"):
            continue
        absolute = urljoin(base_url, candidate)
        if absolute in seen:
            continue
        seen.add(absolute)
        resolved.append(absolute)

    return tuple(resolved)


def needs_render_fallback(fetch: FetchResult, jd_text: str) -> bool:
    """True when the httpx fetch is unusable and a render fallback should be tried."""
    if not fetch.ok:
        return True
    if not fetch.html.strip():
        return True
    return not has_sufficient_jd_text(jd_text)


def extract_posting(
    url: str,
    *,
    http_fetch: Callable[[str], FetchResult],
    render_fetch: Callable[[str], FetchResult] | None = None,
    image_downloader: Callable[[tuple[str, ...], str], tuple[str, ...]] | None = None,
    artifacts_dir: str = "artifacts/position_registration",
) -> ExtractedPosting:
    """Fetch and parse a posting: httpx-first, render fallback, then parse + image evidence.

    Fail-closed: when blocked/empty and no company/role can be recovered, returns
    ``ExtractedPosting(ok=False, reason=...)`` without raising.
    """
    fetch = http_fetch(url)
    company, role, jd_text = ("", "", "")
    if fetch.ok and fetch.html.strip():
        company, role, jd_text = extract_company_role_jd(fetch.html)

    used_fetch = fetch

    if render_fetch is not None and needs_render_fallback(fetch, jd_text):
        rendered = render_fetch(url)
        if rendered.ok and rendered.html.strip():
            r_company, r_role, r_jd = extract_company_role_jd(rendered.html)
            # Prefer the rendered result when it yields more signal.
            if r_company or r_role or has_sufficient_jd_text(r_jd):
                used_fetch = rendered
                company, role, jd_text = r_company, r_role, r_jd

    html = used_fetch.html if used_fetch.html else ""
    fetch_method = used_fetch.fetch_method if used_fetch.fetch_method else "none"

    # Fail-closed: nothing usable came back.
    if not used_fetch.ok and not (company or role):
        reason = used_fetch.reason or "fetch failed and no posting content recovered"
        return ExtractedPosting(
            source_url=url,
            ok=False,
            fetch_method=fetch_method,
            reason=reason,
        )
    if not html.strip() and not (company or role):
        return ExtractedPosting(
            source_url=url,
            ok=False,
            fetch_method=fetch_method,
            reason="empty response and no posting content recovered",
        )
    if not (company or role):
        return ExtractedPosting(
            source_url=url,
            ok=False,
            jd_text=jd_text,
            fetch_method=fetch_method,
            reason="no company or role extracted",
        )

    image_urls = collect_image_urls(html, url)
    image_evidence_paths: tuple[str, ...] = ()
    if image_downloader is not None and image_urls:
        try:
            image_evidence_paths = image_downloader(image_urls, artifacts_dir)
        except Exception:
            # Image download is best-effort evidence; never fail extraction on it.
            image_evidence_paths = ()

    return ExtractedPosting(
        source_url=url,
        ok=True,
        company=company,
        role=role,
        jd_text=jd_text,
        image_urls=image_urls,
        image_evidence_paths=image_evidence_paths,
        fetch_method=fetch_method,
        reason="",
    )


# --- runtime adapters (LAZY imports; NEVER called from tests) -------------------


def httpx_fetch(url: str) -> FetchResult:
    """Runtime adapter: fetch ``url`` with httpx. Lazy import so module import never fails."""
    try:
        import httpx  # lazy import inside adapter body
    except Exception as exc:  # pragma: no cover - runtime-only path
        return FetchResult(url=url, ok=False, fetch_method="httpx", reason=f"httpx unavailable: {exc}")
    try:
        with httpx.Client(follow_redirects=True, timeout=20.0) as client:
            response = client.get(
                url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0 Safari/537.36"
                    )
                },
            )
        ok = response.status_code == 200 and bool(response.text.strip())
        return FetchResult(
            url=url,
            ok=ok,
            status_code=response.status_code,
            html=response.text,
            fetch_method="httpx",
            reason="" if ok else f"http status {response.status_code}",
        )
    except Exception as exc:  # pragma: no cover - runtime-only path
        return FetchResult(url=url, ok=False, fetch_method="httpx", reason=str(exc))


def playwright_fetch(url: str) -> FetchResult:
    """Runtime adapter: render ``url`` with Playwright. Lazy import so module import never fails."""
    try:
        from playwright.sync_api import sync_playwright  # lazy import inside adapter body
    except Exception as exc:  # pragma: no cover - runtime-only path
        return FetchResult(url=url, ok=False, fetch_method="playwright", reason=f"playwright unavailable: {exc}")
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.goto(url, wait_until="networkidle", timeout=30000)
                html = page.content()
            finally:
                browser.close()
        ok = bool(html.strip())
        return FetchResult(
            url=url,
            ok=ok,
            status_code=200 if ok else 0,
            html=html,
            fetch_method="playwright",
            reason="" if ok else "empty rendered content",
        )
    except Exception as exc:  # pragma: no cover - runtime-only path
        return FetchResult(url=url, ok=False, fetch_method="playwright", reason=str(exc))


def _canonical_no_query(url: str) -> str:
    """Internal helper kept out of the public surface; used by adapters if needed."""
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
