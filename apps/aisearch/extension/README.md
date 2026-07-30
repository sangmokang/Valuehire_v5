# Valuehire Automation Banner (AC-8/D9)

자동화가 특정 탭을 조작 중일 때 그 탭 상단에 빨간 띠 오버레이
("🤖 자동화 작업 중 — Valuehire")를 표시하고, 끝나면 제거하는
Manifest V3 크롬 익스텐션입니다.

## 로드 방법 (개발자 모드)

1. 크롬에서 `chrome://extensions` 를 엽니다.
2. 우측 상단 **개발자 모드**를 켭니다.
3. **압축해제된 확장 프로그램을 로드** 클릭 → 이 폴더
   (`apps/aisearch/extension/`)를 선택합니다.
4. 사람인·잡코리아·링크드인 페이지에서 content script 가 자동 주입됩니다.

## 신호 프로토콜

자동화(파이썬)가 CDP 로 페이지 컨텍스트에 아래 이벤트를 dispatch 하면
배너가 표시/제거됩니다:

```js
window.dispatchEvent(new CustomEvent("valuehire:automation",
  {detail: {active: true, task: "사람인 서치 3페이지"}}));  // 표시
window.dispatchEvent(new CustomEvent("valuehire:automation",
  {detail: {active: false, task: ""}}));                      // 제거
```

파이썬 쪽에서는 `apps/aisearch/core/banner.py` 의
`build_dispatch_snippet(active, task)` 로 위 스니펫 문자열을 생성합니다
(실행은 상위 CDP 레이어 몫 — 이 모듈은 브라우저를 호출하지 않습니다).
