# Deprecated: outstanding-news-scraper

Use `/Users/kangsangmo/.claude/skills/outstanding-news/SKILL.md`.

Do not use the old GraphQL/API scraping flow. ValueHire SOT16 requires the
canonical browser DOM collector:

```bash
cd /Users/kangsangmo/Desktop/valuehire_v4
node tools/outstanding-news-collect/browser-collect.mjs \
  --headed --dry-run --target-source customers --limit-companies 1 --limit-articles 1
```

The cron default is:

```text
scripts/launchd/com.valuehire.outstanding-news.plist
-> tools/hermes-agent/valuehire-outstanding-news.sh
-> tools/outstanding-news-collect/browser-collect.mjs
```
