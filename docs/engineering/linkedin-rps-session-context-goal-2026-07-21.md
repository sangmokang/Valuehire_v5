# LinkedIn RPS session-context preservation — goal (2026-07-21)

GitHub issue: #156

## Escaped defect

During a live `humansearch` run, the owner completed LinkedIn Recruiter authentication, but
candidate traversal repeatedly landed on `enterprise-authentication/sessions`. The run had
discarded each result link's query string and then deep-linked to the bare
`/talent/profile/<id>` URL. Blocking detection ran after extraction, screenshot, and archive,
so one session-conflict page was stored as if it were a candidate.

## Reused prior work

- Memory: reuse the one managed Recruiter session; never automate captcha, 2FA, or session
  termination choices.
- Code: extend `humansearch_cdp_run.py` rather than introducing another browser driver.
- Skills/docs: carry forward `task/owner-yield-60s-portal-scope`; do not reimplement its
  60-second, three-portal activity detector.

## Acceptance criteria

### Machine-verifiable

1. Search harvesting retains both a canonical candidate URL and the exact visible result-link
   href used for navigation, including its search context/query.
2. Profile traversal uses that exact navigation href when present. A canonical bare profile URL
   remains storage/dedup identity only.
3. A missing existing Recruiter target fails closed. The runner never creates a new tab or browser.
4. Login/session-conflict markers are checked immediately after each navigation and before
   extraction, screenshot, archive, scoring, or retry.
5. `enterprise-authentication/sessions`, `multiple sign-ins`, and `Only one session` stop the
   traversal once. They never trigger automatic login, confirm, session termination, or repeated
   navigation.
6. Installed Claude and Codex `login`, `humansearch`, `url`, and AI-search skills state the same
   rules: reuse an authenticated exact target, preserve result-link context, and stop on session
   conflict.
7. Owner activity is scoped to actual foreground Saramin, JobKorea, or LinkedIn use and resumes
   after 60 seconds, reusing the already-verified implementation from the prior branch.

### Judgment-verifiable

- User-facing guidance distinguishes an authentication failure from a session-context traversal
  defect and does not blame the user for logging in incorrectly.
- No instruction asks an agent to close a user window/tab/profile or choose which Recruiter
  session to terminate.

## Out of scope

- Automating Cloudflare, captcha, 2FA, or the Recruiter session-selection confirmation.
- Candidate outreach, ClickUp/Discord registration, or sending messages.
