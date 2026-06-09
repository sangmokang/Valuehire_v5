# Search Access Reference

Last updated: 2026-06-08 KST

This document stores search-operation access points for Valuehire AI Search work. Secrets are intentionally not committed here. Put passwords, JWTs, and service keys in a password manager, `.env.local`, or deployment secrets.

## Security Rules

- Do not commit Supabase service role keys, portal passwords, or LinkedIn passwords.
- `.env` and `.env.*` are gitignored in this repo; use `.env.local` for local-only secrets.
- Treat any credential pasted into chat as exposed. Rotate service role keys and passwords before production use.
- Use the Supabase service role key only in server-side code and never in client/browser code.
- Never write Discord bot tokens, portal passwords, JWTs, or service keys in this document. Record only account names, IDs, storage locations, and rotation notes.

## Discord Bot Runtime

| Item | Current standard |
| --- | --- |
| Production bot name | `hermes_v5` |
| Production bot / client ID | `1512101118543397056` |
| Token storage | Local repo: `.env.local` as `DISCORD_BOT_TOKEN`; Hermes Gateway runtime: `~/.hermes/.env` as `DISCORD_BOT_TOKEN` |
| Client ID storage | Local repo and Hermes Gateway runtime both use `DISCORD_CLIENT_ID=1512101118543397056` |
| Token handling rule | Do not paste or commit the token. Verify by Discord API bot ID or SHA-256 fingerprint only. |
| Runtime note | After changing `~/.hermes/.env`, restart Hermes Gateway so the running Discord process loads the new token. |

Server-channel command env:

```bash
DISCORD_ALLOWED_CHANNEL_IDS=123456789012345678,234567890123456789
DISCORD_ALLOWED_ROLE_IDS=345678901234567890
DISCORD_ALLOW_DM_COMMANDS=1
```

Server channels fail closed unless `DISCORD_ALLOWED_CHANNEL_IDS` contains the channel ID. Inside an allowed channel, a user must either be listed in `Discord Contacts` or have one of `DISCORD_ALLOWED_ROLE_IDS`. Slash command responses should be ephemeral. Bot-mention responses should post only a short public acknowledgement and move status details to DM.

## Discord Contacts

| Name | Alias | Email | Discord ID |
| --- | --- | --- | --- |
| 이상혁 | Rogan | rogan@valueconnect.kr | 1404643716320329728 |
| 김충수 |  | kcs@valueconnect.kr | 834330913469890570 |
| 김형준 | Julian | julian@valueconnect.kr | 1153183633297911848 |

## Supabase

| Item | Value |
| --- | --- |
| Project URL | https://sjldbyfcesinrbkgkqwv.supabase.co |
| Anon public key | Store as `SUPABASE_ANON_KEY` outside git |
| Service role key | Store as `SUPABASE_SERVICE_ROLE_KEY` outside git; server-only |

Recommended local env shape:

```bash
SUPABASE_URL=https://sjldbyfcesinrbkgkqwv.supabase.co
SUPABASE_ANON_KEY=<redacted>
SUPABASE_SERVICE_ROLE_KEY=<redacted>
```

## External Search Accounts

**SOT invariant — auto-login is never disabled.** All three protected portals — Saramin,
Jobkorea, **and LinkedIn RPS** — auto-login from the secret store (`.env.local` / `~/.secrets`
/ Mac Keychain): the runner enters id/password and submits, then runs the search through to
result-card collection. Do not re-introduce a "LinkedIn is session-reuse / human-login only"
restriction. The only guardrails are the safety boundaries below.

| Service | Login / account | Secret storage |
| --- | --- | --- |
| Jobkorea / Saramin | valueconnect | Store password outside git as `JOB_PORTAL_PASSWORD` (or per-portal keys) |
| LinkedIn RPS | sangmokang@valueconnect.kr | Store password outside git as `LINKEDIN_PASSWORD`; the runner auto-logs in like the other portals |

**Safety boundaries (these never change):** a captcha / 2FA / 보안문자 / IP보안 / checkpoint /
이상접근 is never auto-bypassed — on detection the automation stops and alerts a human. Credentials
are loaded only from the secret store (never hardcoded/plaintext). Auto-login + search/collect is
always allowed; external sending (candidate send / InMail / email) stays behind the human approval gate.

Optional local env shape:

```bash
# Preferred: per-portal credentials
SARAMIN_USERNAME=valueconnect
SARAMIN_PASSWORD=<redacted>
JOBKOREA_USERNAME=valueconnect
JOBKOREA_PASSWORD=<redacted>

# Backward-compatible fallback if both portals share one account
JOB_PORTAL_USERNAME=valueconnect
JOB_PORTAL_PASSWORD=<redacted>

# LinkedIn RPS auto-logs in from the secret store, like Saramin/Jobkorea.
# A captcha / 2FA / checkpoint is never bypassed — it pauses for human resolution.
LINKEDIN_USERNAME=sangmokang@valueconnect.kr
LINKEDIN_PASSWORD=<redacted>
```

## Saramin Talent Pool Search

Access URL:

- https://www.saramin.co.kr/zf_user/memcom/talent-pool/main/search

Corporate login URL:

- https://www.saramin.co.kr/zf_user/auth?ut=c&url=https%3A%2F%2Fwww.saramin.co.kr%2Fzf_user%2Fmemcom%2Ftalent-pool%2Fmain%2Fsearch

Login notes:

- Always use the corporate-member flow with `ut=c` for Valueconnect. A non-`ut=c` login can fall into the personal-member flow and must be treated as the wrong route.
- Successful corporate login signals: no visible `로그인` link, visible `로그아웃`, and Talent Pool search DOM such as `input.search_input`, `#career_min`, and `#career_max`.

Operation notes:

- If a popup appears, close it with the `X` button before searching.
- Use the DOM structure below as a reference only. Saramin DOM can change or fail to match the live page, so judge by the visible UI image, labels, and field position first.
- OR and AND conditions must receive keywords only. Never enter full sentences.
- Prepare the keyword set first, then place each keyword into OR / AND / NOT according to the intended boolean logic.
- For current search execution, confirm duplicate candidates against ClickUp and Notion before saving output.

Field behavior:

| Field | Purpose | Input rule |
| --- | --- | --- |
| OR keywords | Alternative matching terms | Add one prepared keyword at a time |
| AND keywords | Required matching terms | Add only concise keywords |
| NOT keywords | Exclusion terms | Add only concise keywords or company/role exclusions |
| Domestic famous university tag | Education signal filter | Use when the search target requires elite domestic school background |
| Career min / max | Experience range | Use select values from `0` to `20` |
| Education | Education filter area | Locate by visible title `학력` / class `talent_filter_tit` |
| Company size | Company-size filter area | Locate by visible title `기업규모` / class `talent_filter_tit` |

DOM references:

OR keyword area:

```html
<div class="search_keyword">
  <span class="search_condition_keyword_wrap">
    <span class="search_choose">
      product manager
      <button type="button" class="search_choose_delete">
        <svg><use xlink:href="#ico_delete"></use></svg>
        <span class="blind">삭제</span>
      </button>
    </span>
  </span>
  <span class="search_condition_keyword_wrap">
    <span class="search_choose">
      project manager
      <button type="button" class="search_choose_delete">
        <svg><use xlink:href="#ico_delete"></use></svg>
        <span class="blind">삭제</span>
      </button>
    </span>
  </span>
  <div class="input_wrap">
    <input type="text" class="search_input" maxlength="30" placeholder="추가할 키워드가 있나요?">
  </div>
</div>
```

AND keyword field:

```html
<input type="text" class="search_input result" maxlength="30">
```

NOT keyword field:

```html
<input type="text" class="search_input result" maxlength="30">
```

Domestic famous university tag:

```html
<div class="special_tag_item">
  <button type="button" class="tag_item selected" data-prokeyscachednode="false">
    <svg class="ico_svg"><use href="#search_tag_svg_edu"></use></svg>
    국내 유명 대학 <em>33,500+</em>
  </button>
</div>
```

Career minimum:

```html
<select id="career_min" name="career_min" title="">
  <option value="">선택</option>
  <option value="0">신입</option>
  <option value="1">1년 이상</option>
  <option value="2">2년 이상</option>
  <option value="3">3년 이상</option>
  <option value="4">4년 이상</option>
  <option value="5">5년 이상</option>
  <option value="6">6년 이상</option>
  <option value="7">7년 이상</option>
  <option value="8">8년 이상</option>
  <option value="9">9년 이상</option>
  <option value="10">10년 이상</option>
  <option value="11">11년 이상</option>
  <option value="12">12년 이상</option>
  <option value="13">13년 이상</option>
  <option value="14">14년 이상</option>
  <option value="15">15년 이상</option>
  <option value="16">16년 이상</option>
  <option value="17">17년 이상</option>
  <option value="18">18년 이상</option>
  <option value="19">19년 이상</option>
  <option value="20">20년 이상</option>
</select>
```

Career maximum:

```html
<select id="career_max" name="career_max" title="">
  <option value="">선택</option>
  <option value="0">신입</option>
  <option value="1">1년 이하</option>
  <option value="2">2년 이하</option>
  <option value="3">3년 이하</option>
  <option value="4">4년 이하</option>
  <option value="5">5년 이하</option>
  <option value="6">6년 이하</option>
  <option value="7">7년 이하</option>
  <option value="8">8년 이하</option>
  <option value="9">9년 이하</option>
  <option value="10">10년 이하</option>
  <option value="11">11년 이하</option>
  <option value="12">12년 이하</option>
  <option value="13">13년 이하</option>
  <option value="14">14년 이하</option>
  <option value="15">15년 이하</option>
  <option value="16">16년 이하</option>
  <option value="17">17년 이하</option>
  <option value="18">18년 이하</option>
  <option value="19">19년 이하</option>
  <option value="20">20년 이하</option>
</select>
```

Filter title references:

```html
<span class="talent_filter_tit">학력</span>
<span class="talent_filter_tit">기업규모</span>
```

## Job Korea Candidate Search

Access URL:

- https://www.jobkorea.co.kr/Corp/Person/Find

Operation notes:

- After login, close all extra buttons/popups with `X` and enter the search page quickly.
- Use the DOM structure below as a reference only. Job Korea DOM can change, so judge by the visible UI image, labels, and field position first.
- Use short prepared keywords for integrated search. Avoid sentence-style queries unless the target workflow explicitly requires broad free-text search.
- In detailed search, set education to `대학교(4년) 졸업` only unless the search requirement says otherwise.
- Confirm duplicate candidates against ClickUp and Notion before saving output.

Field behavior:

| Field | Purpose | Input rule |
| --- | --- | --- |
| Integrated search | Main free keyword search | Enter concise prepared keywords |
| Region tab | Opens region filter | Locate by visible label `지역` |
| Region search | Region keyword entry | Enter location name only |
| Education | Detailed education filter | Select only `대학교(4년) 졸업` |
| Career start / end | Experience range | Enter two-digit max values only when required |

DOM references:

Integrated search:

```html
<input
  id="txtKeyword"
  type="text"
  class="inpText js-autoTotal"
  maxlength="300"
  data-jpath="$.totalkeywordlist"
  value=""
  data-kwrd-type-code="1"
  placeholder="키워드를 자유롭게 입력해보세요"
  data-prokeyscachednode="true"
>
```

Region tab:

```html
<button type="button" class="devTab" data-target="dvWorkArea" data-index="2">
  지역<span id="firstfloorSelectedCnt">1</span>
</button>
```

Education detailed search:

```html
<ul id="ulEducation" class="grid">
  <li>
    <input
      name="education1"
      id="education1"
      type="checkbox"
      checked="checked"
      data-v="1"
      data-t="대학교(4년) 졸업"
    >
    <label for="education1" class="chk">
      <span>대학교(4년) 졸업</span>
    </label>
  </li>
  <li>
    <input
      name="education2"
      id="education2"
      type="checkbox"
      data-v="2"
      data-t="대학(2,3년) 졸업"
    >
    <label for="education2" class="">
      <span>대학(2,3년) 졸업</span>
    </label>
  </li>
  <li>
    <input
      name="education3"
      id="education3"
      type="checkbox"
      data-v="3"
      data-t="대학원 졸업"
    >
    <label for="education3" class="">
      <span>대학원 졸업</span>
    </label>
  </li>
  <li>
    <input
      name="education4"
      id="education4"
      type="checkbox"
      data-v="4"
      data-t="고등학교 졸업 이하"
    >
    <label for="education4" class="">
      <span>고등학교 졸업 이하</span>
    </label>
  </li>
</ul>
```

Region search:

```html
<input
  type="text"
  id="txtWorkingAreaKeyword"
  class="inpText js-autoComInput"
  placeholder="지역명 입력"
  data-prokeyscachednode="true"
>
```

Career range:

```html
<input type="text" id="txtCareerStart" maxlength="2" autocomplete="off" value="">
<input type="text" id="txtCareerEnd" maxlength="2" autocomplete="off" value="">
```

## LinkedIn Talent Search

Search URL:

- https://www.linkedin.com/talent/search?searchKeyword=&start=0&uiOrigin=GLOBAL_SEARCH_HEADER

Operation notes:

- LinkedIn DOM is complex and changes often. Do not rely on DOM structure as the primary control surface.
- Search by reading the visible image/text UI first, then use DOM only as a weak reference when it clearly matches the screen.
- Keep the search logic simple and auditable: prepared keywords, Boolean operators, location, Open to Work, and years of experience.
- `Open to Work` should be searched first and treated as the highest-priority filter/signal.
- Base location should be `South Korea` unless the search request says otherwise.
- Use `Advanced Search` -> `Years of Experience`, then search roughly within the target career range plus 2-3 extra years.
- Confirm duplicate candidates against ClickUp and Notion before saving output.

Keyword logic:

| Field | Purpose | Input rule |
| --- | --- | --- |
| Keywords | Boolean keyword search | Use `AND`, `OR`, and parentheses with prepared keywords |
| Open to Work | Priority availability signal | Check/search this first |
| Location | Base geography | Use `South Korea` |
| Years of Experience | Career range | Use target years plus a rough +2-3 year buffer |

Keywords field reference:

```html
<textarea
  id="free-text-single-value-input__textarea-ember15222"
  rows="3"
  placeholder="enter keywords..."
  data-a11y-focus=""
  data-test-free-text-single-value-facet-textarea=""
  data-live-test-free-text-single-value-facet-textarea=""
></textarea>
```

Boolean keyword examples:

```text
("product manager" OR "project manager" OR PM) AND (SaaS OR platform OR B2B)
("growth" OR "performance marketing") AND (commerce OR marketplace)
```

## ClickUp Lists

| Scope | URL |
| --- | --- |
| FY26 candidates | https://app.clickup.com/9018789656/v/li/901814621142 |
| FY26 clients | https://app.clickup.com/9018789656/v/li/901814621569 |
| FY25 candidates | https://app.clickup.com/9018789656/v/li/901804973549 |
| FY25 clients | https://app.clickup.com/9018789656/v/li/901804973550 |

## Notion Databases

| Scope | URL |
| --- | --- |
| Clients | https://app.notion.com/p/valueconnect/bf4ac94452f842309a5ae1b9defcd072?v=cb396e86df3d4ee7931fd0f28328f765 |
| Candidates | https://app.notion.com/p/valueconnect/99425127dffe4245b867fcc380d39dd9?v=a362c9cd55514694aed65fe97d46d2b3 |

## Search Workflow Notes

- Check existing ClickUp and Notion records before external sourcing so duplicate candidates or clients are not created.
- Use FY26 lists for current search execution unless the work explicitly references FY25.
- Use Discord contacts for operational follow-up and exception handling.
- Keep source links, search terms, and candidate/client evidence in the relevant ClickUp or Notion record.
