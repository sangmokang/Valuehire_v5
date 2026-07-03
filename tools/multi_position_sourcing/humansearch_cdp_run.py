"""humansearch CDP 순회 러너 — raw CDP 단일탭으로 LinkedIn RPS 검색결과를 순회·채점.

판정 코어(humansearch.score_humansearch)는 건드리지 않는다. 이 파일은 *오케스트레이션*:
검색결과 카드 수집 → 프로필 1건씩 열기 → 스크린샷·이력서 추출 → CapturedProfile 빌드 → 채점.
발송(Discord)은 호출자가 eligible_matches_for_send 게이트를 통과시킨 뒤 별도 수행.
"""
from __future__ import annotations

import json
import random
import re
import sys
import time
from collections.abc import Iterable
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.multi_position_sourcing import raw_cdp as cdp
from tools.multi_position_sourcing.humansearch import hard_exclude_reason, score_humansearch
from tools.multi_position_sourcing.humansearch_preflight import assert_live_or_abort
from tools.multi_position_sourcing.models import (
    CapturedProfile,
    EmploymentTenure,
    Position,
)

SEARCH_URL_BASE = (
    "https://www.linkedin.com/talent/search?"
    "searchContextId=8d792952-bca2-4a44-813c-ad5f2c932cd4"
    "&searchHistoryId=21200638244"
    "&searchRequestId=7db88134-b564-4010-9180-562ee16d6770"
    "&uiOrigin=FACET_SEARCH"
)

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


def human_delay(lo: float = 20.0, hi: float = 45.0) -> None:
    time.sleep(random.uniform(lo, hi))


# ── 추출 헬퍼 (LinkedIn Recruiter profile innerText 기반) ──
EXTRACT_JS = r"""(() => {
  const t = document.body ? document.body.innerText : '';
  const name = (document.querySelector('h1') ? document.querySelector('h1').innerText : '').trim();
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


def collect_cards(tab, start: int) -> list[dict]:
    tab.navigate(SEARCH_URL_BASE + f"&start={start}", wait_ms=7000)
    # lazy-load: 결과 리스트를 천천히 스크롤
    for _ in range(8):
        tab.eval("window.scrollBy(0, 900)")
        time.sleep(1.2)
    tab.eval("window.scrollTo(0,0)")
    time.sleep(1.0)
    cards = tab.eval(r"""(() => {
      const seen = new Set(); const out = [];
      for (const a of document.querySelectorAll('a[href*="/talent/profile/"]')) {
        const href = a.href.split('?')[0];
        if (seen.has(href)) continue; seen.add(href);
        const li = a.closest('li');
        out.push({url: href, name:(a.innerText||'').trim(),
                  snippet:(li?li.innerText:'').replace(/\n+/g,' | ').slice(0,200)});
      }
      return out;
    })()""")
    return cards or []


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def runner_hard_exclude(prof: CapturedProfile) -> str | None:
    """러너면 하드제외 — 캡처 직후 적용(results.json 에서 제외). 판정은 단일 출처
    humansearch.hard_exclude_reason 재사용(재구현 금지, SOT5). 채널은 프로필의 source_channel —
    링크드인은 학교컷 미적용, 사람인·잡코리아만 전문대 컷(등록면 PC-C1a 와 동일 규칙)."""
    return hard_exclude_reason(prof, prof.source_channel)


def collect_results(rows: Iterable[dict]) -> list[dict]:
    """results.json 산출 — 하드제외 표시된 행을 뺀다(프리랜서·단기이직 2회+·전문대 0건).

    순서 보존. 열어본 프로필의 스크린샷은 process_profile 에서 이미 저장되므로(save-all), 여기서
    빼는 것은 results.json 산출뿐이다."""
    return [row for row in rows if not row.get("hard_exclude")]


def process_profile(tab, card: dict, idx: int) -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    tab.navigate(card["url"], wait_ms=8000)
    info = tab.eval(EXTRACT_JS)
    name = info.get("name") or card.get("name") or f"cand{idx}"
    education = _clean(info.get("education", "")).replace("School name", "").strip()
    safe = re.sub(r"[^A-Za-z0-9]+", "_", name)[:40] or f"cand{idx}"
    shot = OUT_DIR / f"{idx:02d}_{safe}.png"
    try:
        tab.screenshot(str(shot))
    except Exception as e:
        log(f"  screenshot fail: {e}")
        shot = Path("")
    prof = CapturedProfile(
        profile_url=card["url"],
        source_channel="linkedin_rps",
        visible_text=info.get("full", ""),
        summary=info.get("summary", "") or info.get("headline", ""),
        captured_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
        screenshot_path=str(shot),
        education=education,
        evidence_paths=(str(shot),) if shot else (),
        employment_history=build_tenures(info.get("dates", [])),
    )
    match = score_humansearch(prof, POSITION)
    return {
        "idx": idx,
        "name": name,
        "url": card["url"],
        # 러너면 하드제외(PC-C3a): 캡처 직후 적용 — 프리랜서·단기이직·전문대면 results.json 제외.
        "hard_exclude": runner_hard_exclude(prof),
        "otw": info.get("otw", False),
        "headline": _clean(info.get("headline", "")),
        "education": education,
        "score": match.score,
        "breakdown": match.score_breakdown,
        "why_fit": list(match.why_fit),
        "why_not": list(match.why_not),
        "screenshot": str(shot),
        # 재채점용 원시 필드(채점 상수 변경 시 재오픈 없이 offline re-score 가능)
        "summary": prof.summary,
        "visible_text": prof.visible_text,
        "skills": list(prof.skills),
        "employment_history": [
            {"company": e.company, "start_month": e.start_month, "end_month": e.end_month}
            for e in prof.employment_history
        ],
    }


def main(max_profiles: int = 25, start: int = 0) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    t = cdp.find_page_by_url("searchContextId=8d792952") or cdp.find_page_by_url("linkedin.com/talent/search")
    if not t:
        t = cdp.new_tab("about:blank")
    tab = cdp.attach(t)
    log(f"=== humansearch CDP run | start={start} max={max_profiles} ===")

    cards = collect_cards(tab, start)
    # fail-closed 라이브 게이트 (docs/sot/27): 검색이 살아있는 상태가 아니면(세션 만료/세션충돌/
    # 캡차/로그인 리다이렉트/결과 미렌더) 여기서 PreflightError 로 즉시 중단 — 수집/채점을
    # 시작조차 하지 않는다. 봇처럼 같은 네비게이션을 반복하지 않는다(SOT22 R2).
    assert_live_or_abort(tab)
    log(f"collected {len(cards)} cards on page start={start}")
    all_rows: list[dict] = []
    for i, card in enumerate(cards[:max_profiles], 1):
        try:
            r = process_profile(tab, card, i)
            hx = r.get("hard_exclude")
            tag = "⛔HX  " if hx else ("✅PASS" if r["score"] >= 70 else "  ")
            log(f"{tag} #{i:02d} {r['name']!r} score={r['score']} otw={r['otw']} edu={r['education'][:30]!r}"
                + (f" hard_exclude={hx}" if hx else ""))
            all_rows.append(r)
        except Exception as e:
            log(f"  #{i} ERROR {card.get('name')}: {e}")
        # 러너면 하드제외(PC-C3a): results.json 은 하드제외 뺀 것만(프리랜서·단기이직·전문대 0건).
        (OUT_DIR / "results.json").write_text(
            json.dumps(collect_results(all_rows), ensure_ascii=False, indent=2))
        if i < len(cards[:max_profiles]):
            human_delay()
    tab.close()
    results = collect_results(all_rows)
    excluded = [r for r in all_rows if r.get("hard_exclude")]
    passers = [r for r in results if r["score"] >= 70]
    log(f"=== DONE: {len(all_rows)} opened, {len(excluded)} hard-excluded, "
        f"{len(results)} scored, {len(passers)} passers(>=70) ===")


if __name__ == "__main__":
    mx = int(sys.argv[1]) if len(sys.argv) > 1 else 25
    st = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    main(max_profiles=mx, start=st)
