# GreetingHR / Wrtn Career Page Intake Fallback

Use this when ClickUp position tasks contain only integrity metadata or a short stub, but the public job source is a GreetingHR career page such as `career.wrtn.io/ko/o/<openingId>`.

## Pattern

- Fetch the public role page directly.
- Parse the `#__NEXT_DATA__` JSON script from the HTML.
- Recursively find `openingsInfo` and read fields such as:
  - `openingId`
  - `title`
  - `status`
  - `detail` (HTML JD body)
- Strip HTML tags from `detail` to recover a usable JD for search strategy/scoring.

## Wrtn list-page mapping

For Wrtn career home (`https://career.wrtn.io/ko`), the embedded JSON/list HTML may expose `openingId` + `title` pairs before ClickUp has full JD text. Useful examples observed:

- `119686` — `Backend Engineer` — `https://career.wrtn.io/ko/o/119686`
- `209480` — `Product Engineer` — `https://career.wrtn.io/ko/o/209480`
- `218112` — `AX Product Manager (Ontology)` — `https://career.wrtn.io/ko/o/218112`
- `161729` — `[캬라푸] Product Manager` — `https://career.wrtn.io/ko/o/161729`

## Pitfalls

- Do not conclude that a ClickUp task has no JD just because `text_content` contains only an integrity comment. Check whether the company career page or source URL can reconstruct the full JD.
- Do not rely on browser login for public GreetingHR pages; plain HTTP fetch is enough in most cases.
- The public page can contain large script/state payloads. Extract the JSON script instead of trying to scrape visible text from the full HTML.
- Store the source URL used for reconstruction in the report/comment so the JD provenance is clear.
