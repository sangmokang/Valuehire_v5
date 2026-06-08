# Search DOM Selector Map Draft

Date: 2026-06-08 KST  
Rule: owner-provided DOM values override this draft

Basis and boundary:

- `../Valuehire_v4/docs/sot/11-channel-dom-selectors.md` was read. It is the SSOT for offer/body-copy modal fields, not for Saramin/Jobkorea candidate search result pages.
- This file is therefore a search-page selector draft based on the user's provided selectors plus the v4 selector priority policy.
- Once owner-provided search DOM snapshots exist, replace or promote those selectors above every fallback here.

Selector priority:

1. `name`
2. stable `id`
3. `data-test-*`
4. placeholder/title/label text
5. class fallback

Dynamic IDs and one-off generated classes are not allowed as sole dependencies. Selector failure must be recorded as possible site structure change, not silently ignored.

## Saramin

| Purpose | Primary/Fallback chain | Notes |
| --- | --- | --- |
| Keyword input | `input[name="searchword"]` -> `#searchword` -> `input[placeholder*="검색"]` -> `.search_default input.search_input` | User-provided movement says Korean keyword should be pasted into `.search_default input.search_input`; keep it as observed fallback until stable DOM is confirmed. |
| Search button | `button[name="search"]` -> `button:has-text("검색")` -> `.search_panel .btn_search` | Left-side search button must be explicitly resolved. |
| Detail profile link | owner DOM required -> stable profile href pattern | List pages must not be saved. |
| Captcha/security warning | owner DOM required -> text contains `보안`, `비정상`, `captcha`, `자동입력` | Immediate stop. |

## Jobkorea

| Purpose | Primary/Fallback chain | Notes |
| --- | --- | --- |
| Keyword input | `#txtKeyword` -> `input[name="stext"]` -> `input[placeholder*="검색어"]` | Paste through OS clipboard; select autocomplete standard term. |
| Career start | `#txtCareerStart` -> `input[name="CareerStart"]` | Apply JD years plus buffer. |
| Career end | `#txtCareerEnd` -> `input[name="CareerEnd"]` | Apply JD years plus buffer. |
| Filter search button | `.btnSearchFilter` -> `button:has-text("검색")` | Run after detailed education filter. |
| Detail profile link | owner DOM required -> stable profile href pattern | List pages must not be saved. |
| Captcha/security warning | owner DOM required -> text contains `보안`, `비정상`, `captcha`, `자동입력` | Immediate stop. |

## LinkedIn RPS

| Purpose | Primary/Fallback chain | Notes |
| --- | --- | --- |
| Candidate profile link | `a[href*="/talent/profile/"]` -> `[data-test-profile-link]` | Only `/talent/profile/` is accepted as RPS candidate evidence. |
| InMail send forbidden control | `button:has-text("Send InMail")` -> `button:has-text("보내기")` | Must never click; detector exists only to avoid it. |
| Security/checkpoint warning | owner DOM required -> URL/text contains `checkpoint`, `security`, `verify`, `unusual activity` | Immediate stop. |

## Code Contract

Implemented in `tools/multi_position_sourcing/selectors.py`.

The resolver takes a set of selectors observed in a DOM snapshot and returns the highest-priority matching selector. If none match, it raises `SelectorResolutionError` with `site structure may have changed`.
