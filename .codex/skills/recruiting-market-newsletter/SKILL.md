---
name: recruiting-market-newsletter
description: Build a data-driven recruiting market newsletter for a target company persona. Produces (1) a single-file editorial-dashboard HTML for one issue and (2) optional in-app archive page that accumulates issues + translated industry news. Use when the user asks for a "채용 시장 뉴스레터", "recruiting newsletter", "talent market report", "newsletter 아카이브", or wants to brief a CEO/HR head on competitive hiring landscape from scraped job data (Wanted, LinkedIn, Greenhouse, careers pages, etc.). Also covers translating Silicon Valley / TechCrunch / Fortune / CNBC / Bloomberg / WSJ recruiting news into Korean for archival alongside the brief.
---

## When to use this skill

Use whenever a user wants a published-quality newsletter that turns scraped recruiting data into a competitive hiring brief for one persona company. Typical triggers:

- "스캐터랩(or any company) 채용 시장 뉴스레터를 만들어줘"
- "이 회사가 뽑는 포지션을 시장 동종업계와 비교해서 정리해줘"
- "Talent market report on [company]"
- "Weekly recruiting brief"
- "How is the market hiring for the same positions [Company X] is hiring?"
- Any time the deliverable is a one-page (HTML/print/email) competitive hiring landscape using real public job-posting data.

Skip this skill for:
- Internal HR dashboards (use a regular dashboard component instead).
- Single-company JD analysis without competitive context.
- Resume screening or candidate scoring.

## Inputs required

Before drafting, confirm or gather these. If any is missing, ask the user.

1. **Persona company** — the recipient of the newsletter (e.g., 스캐터랩). Need: name, product/service one-liner, key product metrics if public (MAU, growth, geographies), and the company's currently-open positions.
2. **Peer set (8–10 companies)** — pick from the same dataset; group as Tier-1 (직접 경쟁), Tier-2 (인접 도메인), Tier-3 (다른 도메인이지만 인재 풀 겹침).
3. **Global benchmark (1–2 companies)** — usually OpenAI / xAI / Anthropic / Meta AI for AI personas; FAANG for general tech. Used to anchor compensation expectations.
4. **Source dataset** — scraped CSV/JSON with columns at minimum: `company, job_title, job_url, employment_type, scraped_at`. Date stamp must be ≤ 7 days from publish date.
5. **Publish date** — today's date in YYYY.MM.DD (KST), and the issue number.

## Output structure (8 sections, fixed order)

The newsletter is one HTML file, ~700–900 lines, no external assets, max-width 768px container, print-friendly. Section order is opinionated — do not rearrange.

### 1. Masthead
- Brand wordmark (mono, uppercase, 10–11px, letter-spaced)
- Volume / number / publish date row (mono, muted)
- Title in serif display, 32–38px, ≤ 12 words ("[페르소나] 호 — 채용 시장 브리핑")
- Italic deck (serif, 18–20px) — one sentence promise
- Meta strip (mono, 11.5px) — FOR / DATA / JOBS / 발행 (4 fields)

### 2. Lead paragraph
- Bordered-left accent paragraph
- Serif, 20–22px, italic-friendly
- 4–5 sentences. Open with the persona's count of openings, name 1–2 anchor positions, state how many peer postings are simultaneously live, end with a one-line promise of what the rest of the page delivers.

### 3. KPI grid — "이번 호 한눈에"
- 4 cards in a 4-column grid (collapses to 2 on tablet, 1 on phone)
- Card 1: persona's open positions count
- Card 2: peer cohort total postings
- Card 3 (highlighted with hot accent): hottest position category — mention how many companies are simultaneously hiring it
- Card 4: global benchmark total postings (e.g., xAI 7 + OpenAI 7 = 14)
- Each card: label (mono, 10.5px, uppercase) / value (serif, 38px) / unit (sans, 14px) / footnote (12px, ≤ 32px height)

### 4. Position × Market matching table
The signature section. For each persona role, list which peers are simultaneously hiring something equivalent, plus a 5-dot heat indicator.

| Column | Content | Width |
|---|---|---|
| Position | Persona role + small subtitle (product/team) | 30% |
| Same role at peers | Bullet-separated rivals: "회사명 직무명" | 60% |
| 경쟁 강도 | 5-dot heat (●●●●●), filled by **distinct rival company count** | 90px |

**Heat dot rule (strict):** count distinct **companies**, not job listings. Two listings at the same company = 1 rival.
- 0 distinct rivals → ●○○○○
- 1 → ●●○○○
- 2 → ●●●○○
- 3 → ●●●●○
- 4+ → ●●●●●

If a persona role has zero direct match in the dataset, write "(직접 매칭 없음 — 시장 내 사실상 단독)" — this is a *feature*, not a gap.

### 5. Trend chart — category bars
CSS-only horizontal bars across 6–8 categories. Use this taxonomy by default; adjust if the dataset is in a non-tech domain:

- ML / AI 리서치
- 백엔드 / 인프라
- 프론트엔드 / 모바일
- 제품 / 사업개발
- 운영 / CX / QA
- 디자인 / 마케팅
- HR / 인사
- 기타 (only if > 5% of total)

**Numbers must come from a fresh count of the source dataset, not estimated.** Show absolute count, not percentage. Highlight the top category with `.is-hot` class. Mute the smallest with reduced opacity.

Subhead below chart: 2–3 sentences with one observation about the distribution.

### 6. Peer company cards (2-column grid)
One card per peer in the cohort. Each card:
- Tier tag (직접 경쟁 / 인접 도메인 / 다른 도메인)
- Company name (serif, 18–20px)
- Posting count (right-aligned, mono)
- 3-bullet position list (the most differentiating, not the longest)
- One-sentence editorial note starting with "**주목.**" or "**참고.**" — what to actually do about this company

Cards are visually identical; differentiation is in the tag color and content.

### 7. Global benchmark box
2-column comparison panel with a takeaway band underneath.

| Left col | Right col |
|---|---|
| Global company name (e.g., xAI) | Persona company |
| Equivalent role title | Same-category role at persona |
| Compensation range (if public, exact figures from source) | "공고 내 연봉 미공개" or actual |
| 1–2 supplementary postings | Top supporting roles |

Below: "**시사점.**" paragraph naming the persona's one **structural advantage** (real product proof, scale, market position) and how to surface it in the JD.

### 8. Insights — action items (3 cards)
Numbered 01 / 02 / 03, each with:
- Title (one imperative sentence, ≤ 14 words)
- Body (3–4 sentences)
- Body must reference a specific data point from earlier in the newsletter

Format: serif numeral 36px on left, sans body on right.

### 9. Footer
- Top border 2px solid ink
- Two-column row: publication identity (left) / contact + unsubscribe (right)
- Below: data source disclosure in mono 10.5px — exact crawl dates, sample size, methodology one-liner, disclaimer that this is a draft.

## Design tokens (use these exact values)

```css
:root {
  --paper:        #FAFAF7;   /* page bg */
  --surface:      #FFFFFF;   /* cards */
  --soft:         #F3F1EA;   /* bar tracks */
  --hairline:     #E5E2D9;
  --hairline-2:   #D8D4C8;
  --ink:          #121212;   /* primary text */
  --ink-2:        #3A3A3A;
  --muted:        #6E6A60;
  --muted-2:      #8E897C;
  --accent:       #0A5CFF;   /* primary CTA / accent */
  --accent-soft:  #E6EEFF;
  --hot:          #E04E1B;   /* hottest data */
  --hot-soft:     #FBE6DC;
  --good:         #0F8A5F;
  --good-soft:    #E2F2EB;
  --serif:        "Iowan Old Style", "Apple Garamond", Georgia, "Noto Serif KR", serif;
  --sans:         "Pretendard", -apple-system, BlinkMacSystemFont, "Apple SD Gothic Neo", "Segoe UI", system-ui, sans-serif;
  --mono:         "IBM Plex Mono", "JetBrains Mono", "SFMono-Regular", Menlo, Consolas, monospace;
}
```

Brand-tune the `--accent` to the persona's primary brand color when known (e.g., `#0A5CFF` for default; `#FF6B35` for retro/energy brands; `#10B981` for fintech/health).

Layout invariants:
- Container `max-width: 768px`, side padding 48px desktop / 22px mobile.
- Section vertical rhythm: 56px between sections.
- Hairlines 1px `--hairline`. Grid gutters 1px-thick hairline gaps for tabular grids (KPI, company cards).
- Print: `@media print { .section, .co-card { page-break-inside: avoid; } }`
- Responsive: `@media (max-width: 720px)` collapses 4-col → 2-col, `@media (max-width: 480px)` → 1-col.

## Data verification rules (DO NOT skip)

A previous run of this skill shipped with bar-chart numbers off by 30–40% because they were estimated. Verification is mandatory.

1. **Count from source, not memory.** Run a script over the CSV/JSON; do not eyeball.
2. **Dedupe.** Same `(company, job_title, job_url)` triple = 1 posting, even if scraped twice.
3. **Filter noise.** Listing-page titles ("Careers", "Apply", "Sign in", "1:1 티타임", "공유하기", bare "(...)" patterns) are not jobs. Maintain a denylist.
4. **Heat dots count companies, not listings.** Two postings at one company = 1 rival.
5. **Cross-check at three points** before considering the draft done:
   - KPI peer total = sum of per-company counts in card 6
   - Bar chart total = persona count + peer total
   - Match table heat dots ≤ distinct companies counted from source
6. **Architect verification (mandatory).** After draft, run a STANDARD-tier (sonnet) architect review with the source CSV path. Block on any FAIL finding before publishing.

## Step-by-step workflow

1. **Confirm inputs.** Persona, peer cohort, dataset path, publish date. Use AskUserQuestion if unclear.
2. **Inspect data.** Read 50 rows; understand columns, scrape date, language.
3. **Extract per-company counts** with a small Python script. Save the numbers; reuse them everywhere.
4. **Categorize each posting** into the bar-chart taxonomy. Print the table to confirm.
5. **Build the position-matching table** by string-matching persona roles against peer titles. Distinct-company count = heat.
6. **Draft HTML** using the design tokens above. One file. No external assets except (optional) inline SVG icons.
7. **Render and screenshot** via local HTTP server + Playwright/claude-in-chrome. Verify all 8 sections render and the layout doesn't break at 720/480px.
8. **Architect review** at STANDARD tier. Pass the CSV path. Address any FAIL/BLOCKER before claiming done.
9. **Save** to `docs/product/<domain>/<persona>-newsletter-<issue-or-date>.html`.

## Heuristics worth remembering

- **The persona's strongest section is usually the global box, not the chart.** A clear one-line structural advantage ("4.2M users / 12 hrs weekly / proprietary model X") beats every other framing.
- **An empty matching row is a feature.** "직접 매칭 없음" tells the recipient where they have moat. Don't pad it with stretch-comparisons.
- **Tier-3 peer cards exist for context, not action.** Keep them but flag them as "다른 도메인" so the reader doesn't waste energy on them.
- **Action items must name a specific company and a specific copy change.** "Optimize the JD" is too vague; "라이너의 Mobile RN 공고가 같은 풀을 노린다 — 다음 주 모니터링하고 우리 공고에 일본 동시 운영 차별점을 추가하라" is right.
- **Numbers in the lead paragraph anchor trust for the rest of the page.** If the lead says "41건", that exact number must appear in the KPI grid.

## Archive integration (optional second deliverable)

When the user asks for a board / 게시판 / archive that accumulates newsletters and shows them in-app alongside translated industry news, use this companion structure. The single-issue HTML stays the same — the archive is a thin viewing layer over a list of entries.

### Data shape

```ts
type NewsletterCategory = "market-brief" | "industry-news";

type NewsletterEntry = {
  id: string;                  // stable, lowercase-kebab
  issueLabel: string;          // "Vol.01 No.01" for our briefs, "INDUSTRY" for translations
  category: NewsletterCategory;
  publishedAt: string;         // YYYY-MM-DD
  persona?: string;            // only for market-brief
  title: string;
  deck: string;                // 1-line summary
  tags: string[];              // 2-4 short tags
  // market-brief: link to served HTML file
  htmlPath?: string;           // e.g. "/newsletters/scatterlab-2026-05-08.html"
  // industry-news: translated body
  body?: string;               // 4-6 short paragraphs, Korean polite form
  quote?: string;              // ≤20 words, original language, in quotes
  sourceName?: string;         // "Fortune", "CNBC", "TechCrunch"
  externalUrl?: string;        // canonical original URL
  originalTitle?: string;      // English original title
};
```

### File path conventions

- **Source HTML (single issue)**: `docs/product/<domain>/<persona>-newsletter-<YYYY-MM-DD>.html`
- **Served copy** (Next.js public): `public/newsletters/<id>.html` — copy the source here so iframe can load it
- **Seed data**: `app/<route>/_data/newsletterEntries.ts`
- **Archive component**: `app/<route>/_components/NewsletterArchive.tsx`
- Keep source and served copies in sync — the source is authored, the public copy is deployed.

### Component architecture (3 pieces)

1. **Seed data file** — exports `NEWSLETTER_ENTRIES` sorted by `publishedAt` desc + a `NEWSLETTER_CATEGORY_LABEL` map. Industry-news entries are stored alongside market-briefs, no separate stores.
2. **Archive component** — single export `NewsletterArchive`. Internally splits into `ListView` (filter chips + table) and `ReaderView` (header bar + body). Toggle via local `selected` state. No global state, no data fetching — entries are imported.
3. **Reader rendering** branches on category:
   - `market-brief` → render `<iframe src={htmlPath} />` at 100% / 100% in a white-background container so the editorial HTML keeps its paper look inside the dark app.
   - `industry-news` → render React layout: deck → body (`whiteSpace: pre-line` for `\n\n` paragraph breaks) → quote `<blockquote>` → footer with source name, URL link, fair-use disclaimer.

### Translation rules for industry news

- Source must be authoritative US/EU media. Default whitelist: TechCrunch, The Information, Bloomberg, WSJ, NYT, Wired, Forbes, Business Insider, Axios, Fortune, Reuters, CNBC.
- **Verify URL with WebFetch before adding** — never invent URLs.
- Translation is **summary, not full translation** — 4–6 short paragraphs in Korean polite form. Preserve key numbers, named entities, quotes.
- Quote: max 1 per article, ≤20 words, original language, in quotes. Attribution allowed.
- Always include a fair-use disclaimer block in the footer of the reader view.
- Topical mix to aim for: AI talent war, big-tech layoffs, hiring automation, RTO/remote shifts, immigration/visa policy. Avoid doubling up on one topic.

### GNB / access pattern

If the host app has a workflow-gated layout (e.g., users must enter a company before tabs appear), do NOT bury the archive inside that workflow. The archive is global and should be reachable from the landing screen.

Pattern: a fixed `position: fixed; top: 16px; right: 16px;` accent button labelled "📰 Newsletter" that flips a top-level `view` state to a full-screen archive layout with its own back button. This adds one state, no routing changes, no layout file edits.

### Subscription button

In Korean B2B contexts, an explicit "메일 구독 신청" button is expected even for a POC. Wire it to a toast-only handler ("구독 신청이 접수되었습니다 (POC: 실제 발송 미연동)") — do not auto-collect email addresses without consent.

## Example reference

A working POC built with this skill:
- Single-issue HTML: `docs/product/b2b/scatterlab-newsletter-poc-2026-05-08.html`
- Served copy: `public/newsletters/scatterlab-2026-05-08.html`
- Persona: 스캐터랩 (zeta · AI 엔터테인먼트)
- Data source: `docs/product/b2b/wanted-company-career-job-details-2026-05-08-jobs.csv`
- Peers: 뤼튼 / 라이너 / 노타 / 트웰브랩스 / 에너자이 / 베슬AI / 스콘AI / 에니아이
- Global: xAI / OpenAI
- Archive component: `app/b2b-ver2/_components/NewsletterArchive.tsx`
- Seed: `app/b2b-ver2/_data/newsletterEntries.ts` (1 market-brief + 5 industry-news)
- Industry-news sources used: Fortune (4), CNBC (1) — all URLs verified via WebFetch

## Valuehire_v4 프로젝트 데이터 위치 (반복 작업용 표준)

This skill is repeatedly invoked inside the Valuehire_v4 monorepo (`/Users/kangsangmo/Desktop/Valuehire_v4`). When working there, the data, output paths, and verification commands below are the canonical reference. Always check these locations first before asking the user "where is the scraped data?".

### 1) Scraped recruiting data (CSV — primary source)

All seven CSVs live in `docs/product/b2b/`. Pick by purpose:

| File | Rows | Purpose |
|---|---|---|
| `recruiting-q1-wanted-companies-2026-05-08.csv` | 2,286 | **Master ranking** — every company on Wanted with `wanted_postings` count. Use for KPI counts, peer cohort discovery, persona ranking. Columns: `rank, company, wanted_postings`. |
| `recruiting-q2-dart-with-url-2026-05-08.csv` | 695 | DART-listed (KOSPI/KOSDAQ) companies with verified careers URL. Use when persona is a listed conglomerate subsidiary. |
| `recruiting-q3-non-listed-with-url-2026-05-08.csv` | 97 | Non-listed companies with careers URL. |
| `recruiting-q4-homepage-jobs-2026-05-08.csv` | 155 | Homepage-scraped job counts (sample titles included). Use when Wanted has zero data on the persona (e.g., a 자체 채용 사이트만 운영하는 회사). |
| `wanted-company-career-job-details-2026-05-08-jobs.csv` | 3,198 | **Job detail** rows — full title, JD body, skills. Currently covers AI cohort + xAI/OpenAI only. Columns: `company, wanted_posting_count, job_title, job_url, source_career_url, location, department, employment_type, deadline, responsibilities, requirements, preferred, ..., scraped_at`. |
| `wanted-company-career-job-details-2026-05-08-companies.csv` | 1,253 | Per-company scrape metadata (success rate, visited count). Sanity-check whether job details are actually populated for a target. |
| `wanted-matched-verified-2026-05-07.csv` | 177 | Wanted ↔ careers URL verification (older snapshot). |

**Coverage gap to know:** the `*-jobs.csv` only has detailed JD bodies for the AI cohort POC. For other personas, you have **counts** (q1) and **careers URL** (q2/q3/q4) but **no JD-level depth**. Either (a) accept count-based newsletters or (b) run a fresh scrape before drafting.

### 2) Supabase tables (live state)

Migrations: `supabase/migrations/`. Relevant tables:

| Table | Migration | Purpose |
|---|---|---|
| `pipeline_jds` | `20260508140000_pipeline_jds.sql` | Persisted JDs with `lifecycle_status` (open/holding/closing). Source = `'ai_search' | 'manual' | 'seed' | 'b2b_ver2'`. Per-user (`owner_email`). Only contains JDs the user has actively saved — not a market crawl. |
| `b2b_ai_cache` | `20260508120000_b2b_ai_cache.sql` | Token cache for OpenAI B2B responses. Not a data source. |
| `pipeline_candidates` | `20260507000000_pipeline.sql` | Candidate pipeline. Not used for market briefs. |
| `career_targets_quality` | `20260508044113_career_targets_quality.sql` | Career-target quality metrics. Not used for market briefs. |

**Therefore the canonical data source for market-brief KPIs is the CSV stack, not Supabase.** Supabase is for live application state. If the user says "DB 데이터 검토하라", interpret that as "check both Supabase tables AND the seven CSVs in `docs/product/b2b/`" — and explicitly tell them which one you used.

### 3) Output paths (do not deviate)

| Artifact | Path |
|---|---|
| Authored HTML (master) | `docs/product/b2b/<persona-slug>-newsletter-<YYYY-MM-DD>.html` |
| Served HTML (Next.js public) | `public/newsletters/<persona-slug>-<YYYY-MM-DD>.html` (must mirror master 1:1) |
| Seed data | `app/b2b-ver2/_data/newsletterEntries.ts` (insert in `publishedAt` desc order) |
| Archive UI | `app/b2b-ver2/_components/NewsletterArchive.tsx` (already wired — no edit needed for new issues) |

### 4) Standard Python extraction script

Run from `docs/product/b2b/`. Produces persona stats + auto-suggests peer cohort by domain keywords.

```python
import csv
from pathlib import Path

DATA_DIR = Path("docs/product/b2b")
Q1 = DATA_DIR / "recruiting-q1-wanted-companies-2026-05-08.csv"
JOBS = DATA_DIR / "wanted-company-career-job-details-2026-05-08-jobs.csv"

def load(p):
    with open(p) as f:
        return list(csv.DictReader(f))

q1 = load(Q1)
jobs_idx = {}  # company -> list of job rows
try:
    for r in load(JOBS):
        jobs_idx.setdefault(r["company"], []).append(r)
except FileNotFoundError:
    pass

def persona_stats(name):
    """name: exact wanted company name (e.g., '뤼튼테크놀로지스')."""
    hit = next((r for r in q1 if r["company"] == name), None)
    jobs = jobs_idx.get(name, [])
    return {
        "wanted_rank": int(hit["rank"]) if hit else None,
        "wanted_count": int(hit["wanted_postings"]) if hit else 0,
        "job_detail_rows": len(jobs),
        "job_titles": [j["job_title"] for j in jobs[:30]],
    }

def peer_candidates(domain_keywords, exclude=()):
    """Return companies whose name contains any keyword, sorted by wanted_postings desc."""
    seen, out = set(exclude), []
    for r in q1:
        if r["company"] in seen:
            continue
        if any(kw in r["company"] for kw in domain_keywords):
            out.append((int(r["rank"]), r["company"], int(r["wanted_postings"])))
            seen.add(r["company"])
    return sorted(out, key=lambda x: -x[2])[:20]

# Example
print(persona_stats("뤼튼테크놀로지스"))
print(peer_candidates(["AI","에이아이","스캐터","뤼튼","트웰브","노타","업스테이지"], exclude={"뤼튼테크놀로지스"})[:10])
```

### 5) Multi-persona iterative workflow (반복 작업)

When the user asks to produce **N newsletters at once** (e.g., "뤼튼·매드업·현대오토에버·스푼랩스·여기어때 5개를 만들어 DB 저장"):

1. **Confirm output mode** with AskUserQuestion: 풀 editorial HTML / 축약 / 메타만. Default to 풀 editorial.
2. **Persona discovery loop** — for each persona in the user's list:
   a. Look up `persona_stats(name)` in q1. If `wanted_count == 0`, fall back to q4 homepage scrape; if still 0, mark as "외부 채용 사이트 운영 — 추정치 표기" and proceed with declared estimate.
   b. Decide domain (1 sentence). Build a 6–10-keyword list for `peer_candidates()`. Manually trim to 5–8 Tier-1/2/3 peers. Add 1–2 global benchmarks.
3. **Lock the data sheet** for each persona before drafting:
   ```
   persona, wanted_rank, wanted_count, peers (rank/count), global, top_domains
   ```
   Save it as a comment block at the top of each HTML or in a sidecar JSON.
4. **Parallel HTML generation** — dispatch one `executor-high` agent per persona. Pass: (i) the locked data sheet, (ii) the POC HTML path as template, (iii) the design tokens block, (iv) the 8-section spec. Each agent produces one file under `docs/product/b2b/`.
5. **Mirror to public/** — `cp docs/product/b2b/<slug>-newsletter-<date>.html public/newsletters/<slug>-<date>.html` for each new file.
6. **Seed update** — append N entries to `app/b2b-ver2/_data/newsletterEntries.ts` (category=`market-brief`, htmlPath=`/newsletters/<slug>-<date>.html`). Keep array sorted by `publishedAt` desc.
7. **Render check** — start `npm run dev` (or static server on the `public/` directory) and load each `htmlPath`. Verify the 8 sections + 720px/480px responsive break.
8. **Architect review** — STANDARD tier (`architect-medium` / sonnet). Pass all CSV paths + the new HTML paths. Block on any FAIL/BLOCKER.
9. **Commit pattern** — one commit titled `feat(newsletter): add N market briefs (persona1, ..., personaN)` with the master HTML + public copies + seed update + (optional) skill doc bumps.

### 6) Verification commands (Valuehire_v4 specific)

```bash
# Confirm seed array length
grep -c "^  id:" app/b2b-ver2/_data/newsletterEntries.ts

# Confirm public copies exist for every htmlPath in the seed
node -e "const e=require('./app/b2b-ver2/_data/newsletterEntries.ts'); console.log(e.NEWSLETTER_ENTRIES.filter(x=>x.htmlPath).map(x=>x.htmlPath))" \
  | xargs -I{} test -f public{} && echo OK

# Type-check (must stay green)
npx tsc --noEmit -p .

# Live render
npm run dev   # then open http://localhost:3000/b2b-ver2 and click each new issue
```

### 7) Known pitfalls when working in this repo

- **Wanted has gaps.** 자체 채용 사이트만 쓰는 그룹사(예: 현대오토에버)는 q1에 없다. 그 경우 q4 또는 추정치 사용을 명시하라.
- **JD 본문 깊이 부족.** 대부분 페르소나는 `wanted_posting_count`만 있고 `job_title` 본문은 없다. KPI 카드는 카운트 기반으로 정직하게 쓰고, "직무 분포" 차트는 회사명·직무 키워드 추론(예: "AI Researcher" 5건)으로 적되 "추정"임을 푸터에 명시하라.
- **Sort order matters.** `newsletterEntries.ts`는 `.sort((a,b) => b.publishedAt.localeCompare(a.publishedAt))` 로 마지막에 정렬되므로, 배열 위치가 화면 순서를 바꾸지 않는다. ID 충돌만 피하면 된다.
- **Iframe sandbox.** `market-brief`는 `<iframe src={htmlPath}>`로 렌더되므로 HTML은 self-contained여야 한다. 외부 폰트/이미지 의존 금지.
- **Iframe height 체인 (QA-158 재발방지).** ReaderView iframe은 `height: 100%`로 부모 높이를 참조한다. 따라서 *iframe을 마운트하는 페이지 컨테이너는 반드시 명시적 `height`(px/calc/100vh)를 가져야 한다.* `minHeight`만으로는 자식 `height: 100%` 체인이 0으로 fallback되어 iframe 본문이 0px로 렌더된다(헤더 바·Title까지만 보이고 본문 검정). `app/newsletter/page.tsx`처럼 페이지 wrapper를 만들 때 `height: "calc(100vh - 56px)"; display: flex; flexDirection: column`으로 시작하라.

## Korean tone notes (for ko-KR newsletters)

- Body voice: 존칭 "~입니다", but headlines drop politeness for impact ("~이 가장 뜨겁다", "~를 다음 주에 챙기세요").
- Editorial verbs: "겹친다 / 비켜 있다 / 뽑고 있다 / 빠지고 있다" — concrete, market-oriented.
- Avoid: "최고의", "혁신적", "글로벌 리딩" — marketing fluff. Show numbers instead.
- Brand names in Korean+English: 스캐터랩(Scatterlab) on first mention, 스캐터랩 thereafter.
