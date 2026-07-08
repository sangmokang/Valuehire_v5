---
name: outstanding-news
description: "Run, inspect, repair, or explain the ValueHire outstanding.kr customer news collector. Use when the user says 아웃스탠딩, 아웃스탠딩 뉴스, outstanding, outstanding news, 고객사 뉴스 수집, company_news, or asks about the outstanding-news cron/SQLite/browser scraping pipeline."
---

# Outstanding News

Use the repository canonical path `/Users/kangsangmo/Desktop/valuehire_v4`.

## Required Reading

Read these before acting:

- `AGENTS.md`
- `CLAUDE.md`
- `docs/sot/16-outstanding-news-browser-collect.md`
- `docs/sot/13-scheduled-agents-registry.md`
- `tools/outstanding-news-collect/browser-collect.mjs`
- `tools/hermes-agent/valuehire-outstanding-news.sh`
- `scripts/launchd/com.valuehire.outstanding-news.plist`

## Hard Rules

- Reuse `tools/outstanding-news-collect/browser-collect.mjs`. Do not create a new scraper.
- Do not call outstanding.kr GraphQL, REST, or page-internal fetch directly. SOT16 requires browser DOM scraping only.
- Default target source is `customers`: ClickUp `고객사명` custom-field options first, `/admin/clients` persisted `admin_clients` active rows second, then `notion_clients` excluding `Phase Out` and `취소`.
- Store evidence locally in SQLite and artifacts before claiming success: `data/outstanding-news.db` and `data/outstanding-news-runs/`.
- Supabase write requires `OWNER_SIGNOFF_SOURCE_COLLECTION=approved`. ClickUp, Notion, Gmail, Discord, or admin writes are separate L3 actions.

## Commands

Headed browser inspection, SQLite/artifact only:

```bash
cd /Users/kangsangmo/Desktop/valuehire_v4
OUTSTANDING_NEWS_RUN_ID="inspect-$(date -u +%Y%m%dT%H%M%SZ)" \
node tools/outstanding-news-collect/browser-collect.mjs \
  --headed --dry-run --target-source customers \
  --limit-companies 1 --limit-articles 1 --max-search-pages 1 --qa-sample 1 \
  --run-artifact "data/outstanding-news-runs/inspect-latest.json"
```

Cron-equivalent dry run:

```bash
cd /Users/kangsangmo/Desktop/valuehire_v4
VALUEHIRE_OUTSTANDING_DRY_RUN=1 \
VALUEHIRE_OUTSTANDING_LIMIT_COMPANIES=0 \
VALUEHIRE_OUTSTANDING_LIMIT_ARTICLES=0 \
VALUEHIRE_OUTSTANDING_MAX_SEARCH_PAGES=100 \
VALUEHIRE_OUTSTANDING_QA_SAMPLE=5 \
bash tools/hermes-agent/valuehire-outstanding-news.sh
```

Production write path, only after current-turn owner signoff:

```bash
cd /Users/kangsangmo/Desktop/valuehire_v4
OWNER_SIGNOFF_SOURCE_COLLECTION=approved \
node tools/outstanding-news-collect/browser-collect.mjs \
  --write --target-source customers \
  --limit-companies 0 --limit-articles 0 \
  --max-search-pages 100 --qa-sample 5
```

Cron liveness:

```bash
launchctl print gui/$(id -u)/com.valuehire.outstanding-news
launchctl kickstart -k gui/$(id -u)/com.valuehire.outstanding-news
```

## Verification

Check these before reporting completion:

```bash
npm run strict:gate
npx vitest run tools/outstanding-news-collect/tests/browser-collect-batch.test.mjs
bash -n tools/hermes-agent/valuehire-outstanding-news.sh
plutil -lint scripts/launchd/com.valuehire.outstanding-news.plist "$HOME/Library/LaunchAgents/com.valuehire.outstanding-news.plist"
sqlite3 data/outstanding-news.db "select count(*), sum(case when pushed=0 then 1 else 0 end) from company_news_stage;"
```

Report exact artifact path, companies scanned, saved count, pending count, and whether `screenshot_path` and `dom_text_path` files exist.
