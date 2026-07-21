# ClickUp AI Search: channel fallback notes

Use this when executing Valuehire AI Search through step 3/4 and normal search engines or LinkedIn are constrained.

## ClickUp intake token loading

- Preferred token names remain `CLICKUP_API_TOKEN` or `CLICKUP_TOKEN`.
- If `source .env.local` does not expose the token in a terminal command, parse `.env.local` directly in a short script and never print the value. It is acceptable to print only presence/length for debugging, not the token.
- Keep ClickUp intake via API; do not switch to browser login.

## Search engine constraints

- Bing web UI may present a Cloudflare/human verification challenge. Do not click or try to solve it unless explicitly asked.
- Bing RSS/HTML can return irrelevant dictionary/general results for strict quoted LinkedIn X-ray queries. Treat poor RSS output as channel limitation, not as evidence that no candidates exist.
- DuckDuckGo HTML may return the lite search page without parsed results. Retry with another channel rather than concluding no candidates.

## GitHub as fallback discovery channel

When LinkedIn/search engines are constrained, GitHub can still provide public candidate evidence:

1. Search GitHub users by location/company/keyword, e.g.
   - `location:Korea machine learning pytorch`
   - `location:Seoul deep learning pytorch`
   - `location:Korea upstage ai`
   - `NAVER "Machine Learning Engineer" location:Korea`
2. Prefer authenticated GitHub API if available, but do not print `GITHUB_TOKEN`.
3. If GitHub API rate limits, direct GitHub profile HTML pages can still be fetched and inspected for public profile text.
4. Useful public profile fields: current company, title, location, bio, external links, pinned repositories, meta description.
5. If a GitHub profile exposes a LinkedIn URL, record the URL as a source link, but do not claim LinkedIn content was verified if LinkedIn returns HTTP 999 or blocks access.

## Scholar / research evidence

- For research-heavy AI candidates, Google Scholar pages can validate affiliation, degree/research depth, and publication topics.
- Extract only public professional evidence: affiliation, research topics, paper titles, patents. Do not collect private contact details.

## Reporting constraints

- In 3단계, distinguish "lead discovered" from "scored candidate". Only 4단계 should assign match_score and recommended action.
- If discovery is channel-limited, explicitly report which channels were limited and which public sources were actually verified.
- Lower Evidence Quality when seniority, production/MLOps, leadership, or business collaboration are not publicly confirmed.
