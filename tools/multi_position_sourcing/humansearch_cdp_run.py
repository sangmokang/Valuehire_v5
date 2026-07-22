"""humansearch CDP 순회 러너 — raw CDP 단일탭으로 LinkedIn RPS 검색결과를 순회·채점.

판정 코어(humansearch.score_humansearch)는 건드리지 않는다. 이 파일은 *오케스트레이션*:
검색결과 카드 수집 → 프로필 1건씩 열기 → 스크린샷·이력서 추출 → CapturedProfile 빌드 → 채점.
발송(Discord)은 호출자가 eligible_matches_for_send 게이트를 통과시킨 뒤 별도 수행.
"""
from __future__ import annotations

import json
import math
import random
import re
import sys
import time
from collections.abc import Iterable
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.multi_position_sourcing import raw_cdp as cdp
from tools.multi_position_sourcing.harvest_policy import deterministic_delay_ms, worker_should_yield
from tools.multi_position_sourcing.humansearch import (
    hard_exclude_reason,
    plan_result_count_traversal,
    score_humansearch,
)
from tools.multi_position_sourcing.scoring import tenure_months
from tools.multi_position_sourcing.humansearch_preflight import PreflightError
from tools.multi_position_sourcing.humansearch_preflight import assert_not_blocked_or_abort
from tools.multi_position_sourcing.humansearch_preflight import assert_live_or_abort
from tools.multi_position_sourcing.models import (
    CapturedProfile,
    EmploymentTenure,
    Position,
)
from tools.multi_position_sourcing.owner_activity import detect_owner_activity_snapshot
from tools.multi_position_sourcing.session_guard import _default_login_lease
from tools.multi_position_sourcing.session_guard import resolve_existing_target

SEARCH_URL_BASE = (
    "https://www.linkedin.com/talent/search?"
    "searchContextId=8d792952-bca2-4a44-813c-ad5f2c932cd4"
    "&searchHistoryId=21200638244"
    "&searchRequestId=7db88134-b564-4010-9180-562ee16d6770"
    "&uiOrigin=FACET_SEARCH"
)

PAGE_SIZE = 25

OUT_DIR = Path.home() / ".vh-search-results" / "linkedin_rps" / date.today().isoformat() / "ax-sales-lead"
LOG = OUT_DIR / "run.log"

# ── 뤼튼 AX Sales Team Lead JD → 키워드 ──
POSITION = Position(
    position_id="86ey2cdfj",
    company_name="뤼튼테크놀로지스 AX CIC",
    role_title="AX Sales Team Lead (AI Account Executive 리드)",
    jd_text="플레잉 리드 — 본인이 직접 대형 B2B/G 딜 발굴·클로징 + 세일즈 팀 성과/성장 책임. GTM·세일즈 플레이북 수립.",
    must_haves=(
        "sales", "b2b", "account", "deal", "revenue", "negotiat",
        "client", "pipeline", "closing", "영업", "세일즈",
    ),
    nice_to_haves=(
        "b2g", "government", "ai", "saas", "gtm", "go-to-market",
        "0 to 1", "leadership", "team lead", "playbook", "enterprise",
    ),
    source_url="https://app.clickup.com/t/86ey2cdfj",
)


def log(msg: str) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with LOG.open("a") as f:
        f.write(line + "\n")


def human_delay(lo: float = 180.0, hi: float = 420.0) -> None:
    time.sleep(random.uniform(lo, hi))


# ── 추출 헬퍼 (LinkedIn Recruiter profile innerText 기반) ──
EXTRACT_JS = r"""(() => {
  const t = document.body ? document.body.innerText : '';
  const h1Name = (document.querySelector('h1') ? document.querySelector('h1').innerText : '').trim();
  const titleName = (document.title || '').replace(/\s*\|\s*LinkedIn\s*$/i, '').trim();
  // Recruiter can keep the search project in the first h1 while the standalone
  // profile is already loaded. Its document title is the stable candidate name.
  const name = location.pathname.includes('/talent/profile/') &&
    titleName && !/^LinkedIn Talent Solutions$/i.test(titleName)
      ? titleName : h1Name;
  const otw = /open to work/i.test(t);
  // headline: h1 다음 줄 근방 — '· 2nd' 위쪽 한 줄
  let headline = '';
  const hm = t.match(/(?:· \d(?:st|nd|rd|th))\s*\n([^\n]{8,140})/);
  if (hm) headline = hm[1].trim();
  // Summary 블록
  let summary = '';
  const sm = t.split(/\nSummary\n/);
  if (sm.length > 1) summary = sm[1].split(/\n(?:Open to work|Experience|Locations)\n/)[0].trim().slice(0,600);
  // Education 블록
  let education = '';
  const em = t.split(/\nEducation\n/);
  if (em.length > 1) education = em[1].split(/\n(?:Skills|Accomplishments|Interests|Languages)\b/)[0].trim().slice(0,300);
  // 경력 날짜 구간들: 'Mon YYYY – Mon YYYY' / 'Mon YYYY – Present'
  const dates = [...t.matchAll(/([A-Z][a-z]{2})\s+(\d{4})\s*[–-]\s*(Present|[A-Z][a-z]{2}\s+\d{4})/g)]
    .map(m => ({start: m[1]+' '+m[2], end: m[3]}));
  return {name, headline, otw, summary, education, dates, full: t.slice(0, 8000)};
})()"""

_MON = {m: i for i, m in enumerate(
    ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"], start=1)}


def _to_ym(s: str) -> str:
    m = re.match(r"([A-Z][a-z]{2})\s+(\d{4})", s)
    if not m:
        return ""
    return f"{m.group(2)}-{_MON.get(m.group(1),1):02d}"


def build_tenures(dates: list[dict]) -> tuple[EmploymentTenure, ...]:
    out = []
    for d in dates:
        start = _to_ym(d["start"])
        end = "" if d["end"] == "Present" else _to_ym(d["end"])
        if start:
            out.append(EmploymentTenure(company="", start_month=start, end_month=end))
    return tuple(out)


def _search_url(start: int) -> str:
    return SEARCH_URL_BASE + f"&start={start}"


def _run_mutation_guard(mutation_guard) -> None:
    if mutation_guard is not None:
        mutation_guard()


def _mark_busy_or_abort(tab, *, mutation_guard=None) -> None:
    current_url = str(tab.eval("location.href") or "")
    marker = getattr(tab, "mark_busy", None)
    _run_mutation_guard(mutation_guard)
    if not callable(marker) or marker(
        "Codex:humansearch",
        expected_url=current_url,
    ) is not True:
        raise _profile_context_error("automation badge could not be proven on exact target")


def navigate_results_page(tab, start: int, *, mutation_guard=None) -> None:
    _run_mutation_guard(mutation_guard)
    tab.navigate(_search_url(start), wait_ms=7000)


def extract_cards_from_current_page(tab, *, mutation_guard=None, live_check=None) -> list[dict]:
    # lazy-load: 결과 리스트를 천천히 스크롤
    for _ in range(8):
        if live_check is not None:
            live_check(tab)
        _run_mutation_guard(mutation_guard)
        tab.eval("window.scrollBy(0, 900)")
        time.sleep(1.2)
    if live_check is not None:
        live_check(tab)
    _run_mutation_guard(mutation_guard)
    tab.eval("window.scrollTo(0,0)")
    time.sleep(1.0)
    if live_check is not None:
        live_check(tab)
    cards = tab.eval(r"""(() => {
      const seen = new Set(); const out = [];
      for (const a of document.querySelectorAll('a[href*="/talent/profile/"]')) {
        const navigation_url = a.href;
        const href = navigation_url.split('?')[0];
        if (seen.has(href)) continue; seen.add(href);
        const li = a.closest('li');
        out.push({url: href, navigation_url, name:(a.innerText||'').trim(),
                  source_search_url:location.href,
                  snippet:(li?li.innerText:'').replace(/\n+/g,' | ').slice(0,200)});
      }
      return out;
    })()""")
    return cards or []


def collect_cards(tab, start: int, *, mutation_guard=None, badge_guard=None) -> list[dict]:
    navigate_results_page(tab, start, mutation_guard=mutation_guard)
    assert_not_blocked_or_abort(tab)
    if badge_guard is not None:
        badge_guard(tab)
    return extract_cards_from_current_page(
        tab,
        mutation_guard=mutation_guard,
        live_check=assert_not_blocked_or_abort,
    )


def _scope_values(url: str) -> dict[str, str]:
    parts = urlsplit(str(url or ""))
    if parts.scheme != "https" or parts.netloc.lower() != "www.linkedin.com":
        return {}
    query = parse_qs(parts.query)
    scope: dict[str, str] = {}
    for key in ("searchContextId", "searchHistoryId", "searchRequestId", "project"):
        value = str((query.get(key) or [""])[0]).strip()
        if value:
            scope[key] = value
    project_match = re.match(r"^/talent/hire/([^/]+)/", parts.path)
    if project_match and "project" not in scope:
        scope["project"] = project_match.group(1)
    return scope


def resolve_exact_recruiter_target(
    *,
    target_id: str | None = None,
    target_resolver=None,
) -> dict:
    wanted_id = str(target_id or "").strip()
    if not wanted_id:
        raise _profile_context_error("explicit Recruiter target id is required")
    resolver = target_resolver or resolve_existing_target
    try:
        ref = resolver("linkedin_rps", target_id=wanted_id)
    except (LookupError, RuntimeError, ValueError) as error:
        raise _profile_context_error("exact managed Recruiter target could not be resolved") from error
    expected_scope = _scope_values(SEARCH_URL_BASE)
    initial_scope = _scope_values(ref.initial_url)
    initial_parts = urlsplit(ref.initial_url)
    if initial_parts.path.startswith("/talent/profile/"):
        required_keys = ("searchHistoryId",)
    else:
        required_keys = ("searchContextId", "searchHistoryId", "searchRequestId")
    if (
        ref.site != "linkedin_rps"
        or ref.target_id != wanted_id
        or not ref.endpoint.startswith("http://127.0.0.1:")
        or not ref.websocket_url
        or not ref.profile_path
        or ref.browser_pid <= 0
        or any(
            not expected_scope.get(key)
            or initial_scope.get(key) != expected_scope.get(key)
            for key in required_keys
        )
    ):
        raise _profile_context_error("exact managed Recruiter target identity or search scope changed")
    return {
        "id": ref.target_id,
        "url": ref.initial_url,
        "webSocketDebuggerUrl": ref.websocket_url,
        "_endpoint": ref.endpoint,
        "_profile_path": ref.profile_path,
        "_browser_pid": ref.browser_pid,
    }


_RESULT_COUNT_RE = re.compile(
    r"(\d[\d,.]*)([KkMm])?\+?\s*(?:results?|명|개)",
    re.IGNORECASE,
)


def _parse_result_count(raw: str) -> int:
    m = _RESULT_COUNT_RE.search(raw or "")
    if not m:
        raise ValueError(f"검색 결과수를 읽지 못함(fail-closed): {raw!r}")
    number = m.group(1).replace(",", "")
    suffix = (m.group(2) or "").lower()
    value = float(number)
    if suffix == "k":
        value *= 1000
    elif suffix == "m":
        value *= 1_000_000
    return int(math.ceil(value))


def read_result_count(tab) -> int:
    raw = tab.eval(
        r"""(() => {
          const t = document.body ? document.body.innerText : '';
          const m = t.match(/(\d[\d,.]*)([KM])?\+?\s*(?:results?|명|개)/i);
          return m ? m[0] : '';
        })()"""
    )
    return _parse_result_count(str(raw or ""))


def iter_planned_cards(
    tab,
    *,
    result_count: int,
    channel: str = "linkedin",
    start: int = 0,
    page_size: int = PAGE_SIZE,
    pacing_seed: int = 0,
    first_page_cards: list[dict] | None = None,
    mutation_guard=None,
    badge_guard=None,
) -> list[dict]:
    """Collect search cards according to the SOT22 traversal plan.

    PC-C2 owns the result-count decision. This runner only consumes the plan and
    pages through LinkedIn RPS offsets.
    """
    if type(start) is not int or start < 0:
        raise ValueError(f"start must be a non-negative int: {start!r}")
    if type(page_size) is not int or page_size <= 0:
        raise ValueError(f"page_size must be a positive int: {page_size!r}")

    plan = plan_result_count_traversal(channel, result_count)
    if plan.action in {"abort", "add_condition"}:
        return []
    if plan.action == "top_n":
        target = int(plan.limit or 0)
    elif plan.action == "full":
        target = max(0, result_count - start)
    else:
        raise ValueError(f"unsupported traversal action: {plan.action!r}")
    if target <= 0:
        return []

    max_pages = max(1, math.ceil(target / page_size) + 1)
    out: list[dict] = []
    seen_urls: set[str] = set()
    for page_index in range(max_pages):
        offset = start + (page_index * page_size)
        if page_index == 0 and first_page_cards is not None:
            page = first_page_cards
        elif mutation_guard is None:
            page = collect_cards(tab, offset)
        else:
            page = collect_cards(
                tab,
                offset,
                mutation_guard=mutation_guard,
                badge_guard=badge_guard,
            )
        if not page:
            break
        for card in page:
            url = card.get("url") if isinstance(card, dict) else None
            if isinstance(url, str) and url:
                if url in seen_urls:
                    continue
                seen_urls.add(url)
            out.append(card)
            if len(out) >= target:
                break
        if len(out) >= target or len(page) < page_size:
            break
        if page_index < max_pages - 1:
            delay_ms = deterministic_delay_ms(kind="short", step=page_index + 1, seed=pacing_seed)
            time.sleep(delay_ms / 1000)
    return out[:target]


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


_PROFILE_PATH_RE = re.compile(r"^/talent/profile/[^/?#]+$")
_SEARCH_PATH_RE = re.compile(
    r"^/talent/(?:search|hire/[^/]+/discover/recruiterSearch)$",
    re.IGNORECASE,
)
def _profile_context_error(reason: str) -> PreflightError:
    return PreflightError(
        {
            "ok": False,
            "reasons": [reason],
            "checks": {"candidate_profile_context": False},
            "card_count": 0,
        }
    )


def _validate_profile_card_context(card: dict) -> tuple[str, str, str, str]:
    profile_url = str(card.get("url") or "").strip()
    navigation_url = str(card.get("navigation_url") or "").strip()
    source_search_url = str(card.get("source_search_url") or "").strip()
    expected_name = _clean(str(card.get("name") or ""))
    if not expected_name:
        raise _profile_context_error("candidate name missing from Recruiter result")
    if not navigation_url or not source_search_url:
        raise _profile_context_error("profile URL is missing its scoped Recruiter href")

    profile_parts = urlsplit(profile_url)
    navigation_parts = urlsplit(navigation_url)
    profile_is_canonical = (
        profile_parts.scheme == "https"
        and profile_parts.netloc.lower() == "www.linkedin.com"
        and _PROFILE_PATH_RE.fullmatch(profile_parts.path) is not None
        and not profile_parts.query
        and not profile_parts.fragment
    )
    source_parts = urlsplit(source_search_url)
    source_scope = _scope_values(source_search_url)
    navigation_scope = _scope_values(navigation_url)
    scope_keys = {
        "project",
        "searchHistoryId",
        "searchContextId",
        "searchRequestId",
    }
    common_scope = scope_keys & source_scope.keys() & navigation_scope.keys()
    conflicting_scope = {
        key
        for key in common_scope
        if source_scope.get(key) != navigation_scope.get(key)
    }
    shared_scope = common_scope - conflicting_scope
    source_is_search = (
        source_parts.scheme == "https"
        and source_parts.netloc.lower() == "www.linkedin.com"
        and _SEARCH_PATH_RE.fullmatch(source_parts.path) is not None
        and bool(source_scope)
    )
    navigation_is_basic = (
        navigation_parts.scheme == "https"
        and navigation_parts.netloc.lower() == "www.linkedin.com"
        and navigation_parts.path == profile_parts.path
    )
    navigation_is_scoped = (
        navigation_is_basic
        and bool(shared_scope)
        and not conflicting_scope
    )
    if not profile_is_canonical or not source_is_search or not navigation_is_scoped:
        if (
            profile_is_canonical
            and source_is_search
            and navigation_is_basic
            and bool(navigation_scope)
            and (bool(conflicting_scope) or not shared_scope)
        ):
            raise _profile_context_error("profile navigation search scope does not match harvest")
        raise _profile_context_error("profile URL is not an exact scoped LinkedIn Recruiter link")
    return profile_url, navigation_url, source_search_url, expected_name


def _assert_current_profile_identity(tab, profile_url: str) -> None:
    current_url = tab.eval("location.href")
    expected = urlsplit(profile_url)
    current = urlsplit(str(current_url or ""))
    if (
        current.scheme != "https"
        or current.netloc.lower() != "www.linkedin.com"
        or current.path != expected.path
    ):
        raise _profile_context_error("candidate profile identity changed after navigation")


_YEAR_RE = re.compile(r"(19\d{2}|20\d{2})")


def compute_years_experience(
    education: str, employment_history, *, today_year: int, today_month: int = 1
) -> int | None:
    """졸업연도/근속으로 경력연차 산출(PC-I2). fail-closed: 근거 없으면 None(상한 컷 안 되게).

    1) education 의 졸업연도(가장 최신)로 오늘−졸업. 단 education 의 최신 연도가 미래면(재학·졸업예정)
       졸업 경로를 쓰지 않는다 — 시작연도를 졸업으로 오인해 경력을 부풀리지 않는다.
    2) 없으면 근속합산 폴백: tenure_months 재사용(월 정밀). 현재 재직(end 빈값)은 오늘(YYYY-MM)까지.
    3) 둘 다 없으면 None.
    """
    edu = education or ""
    ongoing_edu = "present" in edu.lower() or "현재" in edu or "재학" in edu
    all_years = [int(y) for y in _YEAR_RE.findall(edu)]
    plausible = [y for y in all_years if 1950 <= y <= today_year]
    # 졸업 경로는 (a)미래 연도(졸업 range 끝이 미래) 또는 (b)재학 표기(Present/현재)면 쓰지 않는다 —
    # 시작연도를 졸업으로 오인해 경력을 부풀리지 않는다(V1 Codex). 그 경우 근속합산 폴백으로.
    if plausible and max(all_years) <= today_year and not ongoing_edu:
        return max(0, today_year - max(plausible))

    today_ym = f"{today_year:04d}-{today_month:02d}"
    total_months = 0
    counted = False
    for tenure in employment_history:
        # 현재 재직(end 빈값 또는 Present/현재)은 오늘까지로 월 정밀 계산(tenure_months 재사용).
        end = tenure.end_month
        if not end or end in ("Present", "present", "현재"):
            end = today_ym
        months = tenure_months(tenure.start_month, end)
        if months is not None and months >= 0:
            total_months += months
            counted = True
    return (total_months // 12) if counted else None


def runner_hard_exclude(prof: CapturedProfile) -> str | None:
    """러너면 하드제외 — 캡처 직후 적용(results.json 에서 제외). 판정은 단일 출처
    humansearch.hard_exclude_reason 재사용(재구현 금지, SOT5). 채널은 프로필의 source_channel —
    링크드인은 학교컷 미적용, 사람인·잡코리아만 전문대 컷(등록면 PC-C1a 와 동일 규칙)."""
    return hard_exclude_reason(
        prof, prof.source_channel, seniority_max=POSITION.seniority_max
    )


def collect_results(rows: Iterable[dict]) -> list[dict]:
    """results.json 산출 — 하드제외 표시된 행을 뺀다(프리랜서·단기이직 2회+·전문대 0건).

    순서 보존. 열어본 프로필의 스크린샷은 process_profile 에서 이미 저장되므로(save-all), 여기서
    빼는 것은 results.json 산출뿐이다."""
    return [row for row in rows if not row.get("hard_exclude")]


def owner_snapshot_should_yield(snapshot) -> bool:
    """R4 owner-activity bridge: consume PC-F1 only through worker_should_yield."""
    return worker_should_yield(
        owner_activity_detected=bool(getattr(snapshot, "owner_activity_detected", True))
    )


def _write_results(rows: list[dict]) -> None:
    (OUT_DIR / "results.json").write_text(
        json.dumps(collect_results(rows), ensure_ascii=False, indent=2)
    )


def process_cards_with_r4(
    tab,
    cards: list[dict],
    *,
    owner_snapshot=detect_owner_activity_snapshot,
    live_check=assert_not_blocked_or_abort,
    mutation_guard=None,
    badge_guard=None,
) -> list[dict]:
    """Open cards while respecting owner Chrome yield and mid-run preflight STOP."""
    all_rows: list[dict] = []
    for i, card in enumerate(cards, 1):
        snapshot = owner_snapshot() if callable(owner_snapshot) else owner_snapshot
        if owner_snapshot_should_yield(snapshot):
            log("R4 yield — owner Chrome activity detected; stopping profile traversal")
            break
        try:
            _run_mutation_guard(mutation_guard)
            r = process_profile(
                tab,
                card,
                i,
                live_check=live_check,
                mutation_guard=mutation_guard,
                badge_guard=badge_guard,
            )
            hx = r.get("hard_exclude")
            tag = "⛔HX  " if hx else ("✅PASS" if r["score"] >= 70 else "  ")
            log(f"{tag} #{i:02d} {r['name']!r} score={r['score']} otw={r['otw']} edu={r['education'][:30]!r}"
                + (f" hard_exclude={hx}" if hx else ""))
            all_rows.append(r)
            _write_results(all_rows)
        except PreflightError as e:
            log(f"R4 STOP — live preflight failed during traversal: {e}")
            break
        except Exception as e:
            log(f"  #{i} ERROR {card.get('name')}: {e}")
            _write_results(all_rows)
        if i < len(cards):
            human_delay()
    return all_rows


def process_profile(
    tab,
    card: dict,
    idx: int,
    *,
    live_check=None,
    mutation_guard=None,
    badge_guard=None,
) -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    profile_url, navigation_url, source_search_url, expected_name = (
        _validate_profile_card_context(card)
    )
    guard = live_check or assert_not_blocked_or_abort
    _run_mutation_guard(mutation_guard)
    tab.navigate(navigation_url, wait_ms=8000)
    # Escaped defect #156: a multiple-sign-in page used to be extracted, screenshotted,
    # archived, and scored as a candidate because this check ran only after process_profile.
    # Challenge/session-conflict detection must be the first operation after navigation.
    guard(tab)
    _assert_current_profile_identity(tab, profile_url)
    if badge_guard is not None:
        badge_guard(tab)
    info = tab.eval(EXTRACT_JS)
    name = _clean(str(info.get("name") or ""))
    if not name or name.casefold() != expected_name.casefold():
        raise _profile_context_error("candidate identity mismatch after navigation")
    education = _clean(info.get("education", "")).replace("School name", "").strip()
    safe = re.sub(r"[^A-Za-z0-9]+", "_", name)[:40] or f"cand{idx}"
    shot = OUT_DIR / f"{idx:02d}_{safe}.png"
    guard(tab)
    _assert_current_profile_identity(tab, profile_url)
    _run_mutation_guard(mutation_guard)
    try:
        tab.screenshot(str(shot))
    except Exception as e:
        shot.unlink(missing_ok=True)
        raise RuntimeError("profile screenshot save failed; traversal must not advance") from e
    try:
        guard(tab)
        _assert_current_profile_identity(tab, profile_url)
        _run_mutation_guard(mutation_guard)
    except Exception:
        shot.unlink(missing_ok=True)
        raise
    tenures = build_tenures(info.get("dates", []))
    prof = CapturedProfile(
        profile_url=profile_url,
        source_channel="linkedin_rps",
        visible_text=info.get("full", ""),
        summary=info.get("summary", "") or info.get("headline", ""),
        captured_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
        screenshot_path=str(shot),
        education=education,
        # PC-I2: 졸업연도/근속으로 경력연차 산출 → PC-I1 경력상한 컷의 입력.
        years_experience=compute_years_experience(
            education, tenures, today_year=date.today().year, today_month=date.today().month
        ),
        evidence_paths=(str(shot),) if shot else (),
        employment_history=tenures,
    )
    from tools.multi_position_sourcing.profile_archive_store import ProfileArchiveStore

    hard_exclude = runner_hard_exclude(prof)
    receipt = ProfileArchiveStore().save(
        profile_url=profile_url, channel="linkedin_rps", position_id=POSITION.position_id,
        scenario="humansearch", page=1, candidate_index=idx, screenshot_path=shot,
        resume_text=prof.visible_text, hard_exclude_reason=hard_exclude or "",
    )
    match = None if hard_exclude else score_humansearch(prof, POSITION)
    return {
        "idx": idx,
        "name": name,
        "url": profile_url,
        "navigation_url": navigation_url,
        "source_search_url": source_search_url,
        # 러너면 하드제외(PC-C3a): 캡처 직후 적용 — 프리랜서·단기이직·전문대면 results.json 제외.
        "hard_exclude": hard_exclude,
        "otw": info.get("otw", False),
        "headline": _clean(info.get("headline", "")),
        "education": education,
        "score": match.score if match else 0,
        "breakdown": match.score_breakdown if match else {},
        "why_fit": list(match.why_fit) if match else [],
        "why_not": list(match.why_not) if match else [f"hard_exclude:{hard_exclude}"],
        "screenshot": str(shot),
        "db_row_id": receipt.row_id,
        "save_status": "saved",
        # 재채점용 원시 필드(채점 상수 변경 시 재오픈 없이 offline re-score 가능)
        "summary": prof.summary,
        "visible_text": prof.visible_text,
        "skills": list(prof.skills),
        "employment_history": [
            {"company": e.company, "start_month": e.start_month, "end_month": e.end_month}
            for e in prof.employment_history
        ],
    }


def main(
    max_profiles: int = 25,
    start: int = 0,
    *,
    owner_snapshot=detect_owner_activity_snapshot,
    target_id: str | None = None,
    lease_factory=None,
    target_resolver=None,
) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    lease = (lease_factory or _default_login_lease)("linkedin_rps")
    lease.acquire()
    tab = None
    try:
        mutation_guard = getattr(lease, "assert_owned", None)
        if not callable(mutation_guard):
            raise RuntimeError("LinkedIn profile lease cannot prove ownership")
        mutation_guard()
        t = resolve_exact_recruiter_target(
            target_id=target_id,
            target_resolver=target_resolver,
        )
        mutation_guard()
        tab = cdp.attach(t, badge=False)
        badge_guard = lambda current_tab: _mark_busy_or_abort(
            current_tab,
            mutation_guard=mutation_guard,
        )
        log(f"=== humansearch CDP run | start={start} ===")

        # A login/session-conflict surface must stop before the runner mutates history by
        # navigating to search. Authentication recovery belongs to the exact-target login guard.
        assert_not_blocked_or_abort(tab)
        badge_guard(tab)
        navigate_results_page(tab, start, mutation_guard=mutation_guard)
        # fail-closed 라이브 게이트 (docs/sot/27): 검색이 살아있는 상태가 아니면(세션 만료/세션충돌/
        # 캡차/로그인 리다이렉트/결과 미렌더) 여기서 PreflightError 로 즉시 중단 — 수집/채점을
        # 시작조차 하지 않는다. 봇처럼 같은 네비게이션을 반복하지 않는다(SOT22 R2).
        assert_live_or_abort(tab)
        badge_guard(tab)
        result_count = read_result_count(tab)
        first_page_cards = extract_cards_from_current_page(
            tab,
            mutation_guard=mutation_guard,
            live_check=assert_not_blocked_or_abort,
        )
        cards = iter_planned_cards(
            tab,
            result_count=result_count,
            channel="linkedin",
            start=start,
            pacing_seed=result_count + start,
            first_page_cards=first_page_cards,
            mutation_guard=mutation_guard,
            badge_guard=badge_guard,
        )
        log(f"planned traversal result_count={result_count} collected={len(cards)} start={start}")
        all_rows = process_cards_with_r4(
            tab,
            cards,
            owner_snapshot=owner_snapshot,
            live_check=assert_not_blocked_or_abort,
            mutation_guard=mutation_guard,
            badge_guard=badge_guard,
        )
        results = collect_results(all_rows)
        excluded = [r for r in all_rows if r.get("hard_exclude")]
        passers = [r for r in results if r["score"] >= 70]
        log(f"=== DONE: {len(results) + len(excluded)} opened, {len(excluded)} hard-excluded, "
            f"{len(results)} scored, {len(passers)} passers(>=70) ===")
    finally:
        try:
            if tab is not None:
                safe_for_badge_cleanup = False
                try:
                    assert_not_blocked_or_abort(tab)
                    safe_for_badge_cleanup = True
                except Exception:
                    safe_for_badge_cleanup = False
                if safe_for_badge_cleanup:
                    try:
                        mutation_guard()
                        closed = tab.close()
                    except Exception:
                        closed = False
                    if closed is not True:
                        tab.disconnect()
                else:
                    tab.disconnect()
        finally:
            lease.release()


def _parse_cli_args(argv: list[str]) -> tuple[int, int, str]:
    if len(argv) < 4 or not str(argv[3]).strip():
        raise SystemExit(
            "usage: humansearch_cdp_run.py <max_profiles> <start> <exact_target_id>"
        )
    return int(argv[1]), int(argv[2]), str(argv[3]).strip()


if __name__ == "__main__":
    mx, st, exact_target_id = _parse_cli_args(sys.argv)
    main(max_profiles=mx, start=st, target_id=exact_target_id)
