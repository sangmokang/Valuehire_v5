# 셀렉터·검색흐름 실패 장부 (selectors-error-ledger)

> 붙여주신 방어적 브라우저 지침 원칙4. **다음 실행 시 이 파일을 가장 먼저 읽고** 같은 주소/상황에서
> 같은 실수를 반복하지 않게 방어적으로 작성한다. 위→아래 시간순(최신 위).

| 날짜 | 채널/URL | 친 셀렉터 | 증상(실제 화면 특이점) | 다음 실행 방어책 |
|---|---|---|---|---|
| 2026-06-22 | LinkedIn `/talent/search` | `input[aria-label*="search" i]` | 키워드 되읽기는 일치(필드엔 들어감)인데 Enter 후 URL이 `?uiOrigin=GLOBAL_SEARCH_HEADER`로 가고 결과 0건/카드 0. → **전역 헤더 검색칸**을 잡았고 **리크루터 인재검색 본 필드**가 아니었음. | 헤더 검색 말고 **리크루터 people-search 입력**을 타깃: `/talent/search/` 진입 후 결과 그리드의 검색 필터 영역에서 키워드 박스를 찾는다. `uiOrigin=GLOBAL_SEARCH_HEADER`가 뜨면 잘못 친 것으로 간주(0건을 "후보 없음"으로 결론내지 말 것). 결과 컨테이너 셀렉터(`[data-test-paginator-total]`/result 카드)도 라이브 재확인 필요. |

| 2026-06-22 | 사람인 `/talent-pool/main/search` | (진입 전) | 자동으로 `/talent-pool/main/tutorial` 로 리다이렉트 → 검색폼 없음. 메모리 `valuehire-saramin-talentpool-tutorial-block` 재확인. | 원칙1대로 URL에 `tutorial` 뜨면 계정/온보딩 상태 문제로 분류 → 사장님께 알림(코드로 못 뚫음). 라이브 검색 불가. |
| 2026-06-22 | 잡코리아 `/Corp/Person/Find` | 키워드칸 `#txtKeyword`(ph="키워드를 자유롭게 입력해보세요") | **성공**: 키워드 되읽기 일치 + Enter 후 실제 후보 카드 반환(스크린샷 확인). 단 **총 결과수 요소를 신뢰성 있게 못 집음** — 페이지에 콤마숫자가 많고(만원/이력서총수 `230,220` 등) `명/총/건` 매칭 실패. max()는 페이지 상수 오집. | 키워드칸=`#txtKeyword` 확정(다른 칸 `txtCareerStart/AgeStart` 등 혼동 말 것). 결과 총수는 DOM 텍스트 말고 **결과 헤더 요소를 스크린샷/비전으로 핀포인트** 후 셀렉터 고정 필요. AND/OR 판별은 그 총수 확보 후. |

## 교훈(원칙으로 승격 후보)
- **0건 = "후보 없음"이 아니라 "흐름/필드 의심" 먼저.** 필드 되읽기 일치 + 결과 0이면 **검색 종류(전역 vs 인재검색)·필드 위치**부터 확인. (W4-3 라이브 인수기준에 반영)
- LinkedIn은 `li.protechts.net ...uc=scraping` 비콘 상시 → 자동 검색 최소화·사람 페이스.
