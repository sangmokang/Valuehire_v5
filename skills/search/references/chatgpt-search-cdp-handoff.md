# ChatGPT Search via Chrome DevTools Protocol — Valuehire AI Search

Use this when the user expects ChatGPT Search to be included in Stage 3 candidate discovery and an existing Chrome/ChatGPT tab is available through a local CDP endpoint such as `http://127.0.0.1:9222/json/list`.

## Pattern

1. Build the Stage 3 handoff prompt from the position intake and search strategy.
   - Ask for human-readable candidates first and JSON last.
   - Require LinkedIn URL, profile URL, score/priority, fit reason, education/career summary, direct source URLs, and public recruiting/work contact only when explicitly public.
2. Find the ChatGPT tab from CDP:
   - Prefer the active project conversation URL when known.
   - If multiple ChatGPT tabs exist, inspect title/URL and do not assume the first tab is the right one.
3. Insert the prompt into the composer with CDP `Input.insertText`, submit with Enter, then poll the page.
4. Poll for completion by inspecting assistant messages, not just page body text.
   - Good selector: `[data-message-author-role="assistant"]`.
   - Wait until the stop button is gone: `[data-testid=stop-button]` is false.
   - Require enough content plus markers such as `source_urls`, `JSON`, or a candidate count before treating output as final.
5. Save raw output and normalize:
   - Raw transcript: `/tmp/<position>_chatgpt_search_raw.txt` or similar.
   - Normalized JSON: `/tmp/<position>_chatgpt_search_candidates.json`.
   - Human handoff markdown in the project directory.
6. Re-score/triage the candidates yourself before reporting. ChatGPT Search output is a lead source, not final truth.

## Pitfalls

- Polling the whole `document.body.innerText` too early may capture only the prompt or sidebar text. Use assistant-message elements and wait for completion.
- If the tab keeps saying “답변 마무리 중” or the stop button remains visible, keep polling or save a clearly marked partial; do not report it as done.
- Multiple ChatGPT tabs are common. Wrong-tab capture can create an empty/irrelevant result file.
- Search output may mix service/company metrics with the individual candidate’s own achievements. Mark this in `risk_or_gap` and avoid overstating personal impact.
- LinkedIn may be the only available profile URL for some candidates. That is acceptable as a public lead, but do not claim profile details you did not inspect.

## Minimal verification checklist

- Raw ChatGPT Search output exists and contains assistant output, not just the prompt.
- Candidate JSON parses successfully.
- Each candidate has at least one public URL in `source_urls`.
- Public recruiting/work contact is null/unknown unless explicitly visible as work/recruiting contact.
- Side effects remain zero unless separately approved: no outreach, no DB write, no Kanban/ClickUp update.
