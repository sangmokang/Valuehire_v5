# SOT 23 — 채널별 DOM Selector SSOT

> 출처: `docs/sot/22-talent-search-filters.json`의 `channels.<채널>.dom_selectors`.
> 행동 전 DOM inventory 덤프가 이 표보다 우선합니다. 페이지가 바뀌면 fresh DOM으로 재확인합니다.

---

## saramin

| 키 | 값 |
|---|---|
| `_source` | `saramin SKILL §6(208-217) 라이브 검증 표 + saramin-search-engine.mjs + ai-search-saramin-runner.mjs` |
| `or_keyword_input` | `{"primary":"div.search_default input.search_input","automation_alt":"input.search_input.result","note":"force click 필요 — AI 추천 dropdown overlay 회피. 좌표 폴백 page.mouse.click(210,210)"}` |
| `and_keyword_input` | `div.search_word_include input.search_input` |
| `not_keyword_input` | `div.search_word_except input.search_input` |
| `delete_all_chips` | `button.btn_delete_all, button:has-text("전체삭제"), button:has-text("초기화")` |
| `quick_filter_chip` | `{"selector":"button.tag_item:has-text(\"국내 유명 대학\")","match":"텍스트 매칭"}` |
| `search_button` | `button.search_submit (또는 button filter hasText /^검색$/, getByRole('button',{name:'검색'}))` |
| `result_count` | `{"selector":"span.list_count","text_pattern":"총 N 명","fallbacks":["body.innerText /총\\s+(\\d+)/","em 태그 100+ 또는 0 (페이지번호 1~99 + page/navi 클래스 제외)"],"source":"saramin-search-engine.mjs:15-51"}` |
| `result_card` | `{"selector":"div.talent_list_item","per_page":20}` |
| `candidate_id` | `div.check_area[residx]` |
| `card_detail_link` | `{"selector":"div.talent_list_item div.summary_info a (또는 a[href=\"javascript:void(0)\"] 텍스트>80자)","behavior":"click 시 새 탭 hiring.saramin.co.kr/applicant-view/position/resume/{rNo}"}` |
| `save_button` | `button:has-text("후보자 저장")` |

## jobkorea

| 키 | 값 |
|---|---|
| `_source` | `build-search.mjs CAREER_DOM_SELECTORS + run-search.mjs RESULT_SELECTORS + ai-search-saramin-runner.mjs:351-396` |
| `keyword_input` | `#txtKeyword` |
| `keyword_clear` | `.btnKeywordClear` |
| `career_start_input` | `#txtCareerStart` |
| `career_end_input` | `#txtCareerEnd` |
| `career_newcomer` | `#career_0` |
| `career_overseas` | `#careeroverseas` |
| `career_search_btn` | `#btnCareerSearch (전체 재검색 트리거, 1급 경로)` |
| `keyword_search_btn` | `#btnKeywordSearch` |
| `age_search_btn` | `#btnAgeSearch` |
| `result_row` | `.dvResumeTr` |
| `result_card_name` | `.name a, .tit a, a.name` |
| `result_card_title` | `.career_area .txt, .exp_area .txt, .txt_career` |
| `result_card_link` | `a[href*="/resume/"], a[href*="/person/"]` |
| `headhunter_select` | `input[type=radio][name="choose-headhunter"][data-info]` |

## linkedin

| 키 | 값 |
|---|---|
| `_source` | `linkedin SKILL §3.3(132-141) data-test 6종 + linkedin-search-engine.mjs:124-160` |
| `profile_card_container` | `section[data-test-profile-card]` |
| `full_name` | `[data-test-row-lockup-full-name], h1` |
| `headline` | `[data-test-row-lockup-headline]` |
| `current_company` | `[data-test-current-company]` |
| `current_position` | `[data-test-current-position]` |
| `education_school` | `{"selector":"[data-test-education-school]","note":"학교로 거를 땐 이 텍스트를 후처리 필터로 사용"}` |
| `location` | `[data-test-location]` |
| `result_profile_links` | `{"primary":"a[href*=\"/profile/\"], a[href*=\"/talent/hire/\"]","fallback":"a[href*=\"/in/\"] (혼합 화면, /linkedin\\.com\\/in\\/[^/]+\\/?$/ 필터)","card_container":"a.closest('[data-entity-urn], li, [class*=\"result\"], [class*=\"card\"]')","name_in_card":"[class*=\"name\"], [class*=\"title\"], h3, h4","title_in_card":"[class*=\"subtitle\"], [class*=\"position\"], [class*=\"headline\"]"}` |
