# Goal — login exact-window handoff + safe keepalive

- 작성: 2026-07-18 (`$st`, 사장님 직접 지시)
- 모드: code-change / 위험등급: L3 (로그인 세션·사람 브라우저와 같은 머신의 CDP 조작)
- 정본: `skills/login/` → 저장소 `.claude/skills/login/` 및 사용자 Claude/Codex/Hermes 설치본

## 문제와 재현 근거

- 여러 Chrome 창이 동시에 열려 있으면 에이전트가 어느 브라우저·창·탭에 붙었는지 사람이 알 수 없다.
- 기존 `session_guard`는 쿠키를 읽고 행동 이름만 반환하며 실제 keepalive 왕복을 수행하지 않는다.
- 기존 사람 개입 경로는 900초 timeout, 일반 `bring_to_front`, mutating ready check를 허용해 로그인 중 navigate/click이 반복될 수 있다.
- Python Quartz는 현재 머신에서 `ModuleNotFoundError`지만 Swift CoreGraphics는 실제 `CGWindowID` 175/180을 열거했고 `screencapture -x -l <id>`가 창별 PNG를 만들었다.
- 기존 기본 탭 선택은 URL substring 실패 시 첫 탭으로 폴백해 다른 브라우저를 건드릴 수 있다.

## 단일 성공 기준

정확한 관리 브라우저 endpoint·profile·PID·CDP target을 하나로 결박하고, 그 target과 같은 macOS 창을 유일하게 찾아 사람이 로그인할 창을 한 번 명시한다. `HUMAN_AUTH` 동안에는 읽기만 하며 무기한 기다리고, 인증 뒤에는 검증된 AI 전용 clean tab에서만 안전한 same-origin GET 링크를 한 번 클릭한 다음 같은 target의 브라우저 history entry로 Back하여 원 URL·인증을 다시 증명한다.

## 불변식

1. 새 브라우저·창·탭은 0개다. endpoint나 target이 없거나 여러 개면 fail closed한다.
2. exact endpoint → exact page target → browser PID/profile → `Browser.getWindowForTarget` bounds → 같은 PID의 유일한 `CGWindowID` 순서로만 창을 찾는다. 첫 창·제목 substring·전체 화면 캡처 fallback은 없다.
3. 사용자에게 site, agent, profile, endpoint, target suffix, sanitized URL/title, PID, `CGWindowID`를 한 번 보여주고 그 exact window만 `screencapture -l`로 증명한다.
4. `HUMAN_AUTH` 진입 표시/앞으로 가져오기는 최대 1회다. 이후 navigate/click/type/submit/close/focus-again은 0회이고 5초 이상 간격의 read-only 인증 probe와 OS idle만 읽는다. timeout은 없다.
5. 인증 마커가 보여도 마지막 사람 입력 뒤 15초 quiet가 확인되기 전에는 `AUTHENTICATED`로 전이하지 않는다.
6. keepalive 주기는 사람인·잡코리아 900초, LinkedIn RPS 1800초다. 쿠키 존재만으로 성공 처리하지 않고 쿠키 값은 저장하지 않는다.
7. keepalive 대상은 기존 exact target, AI 전용, clean form, 이전에 검증된 무료·읽기 전용 same-origin GET 링크뿐이다. `target=_blank`, download, 저장/발송/유료/모달/새 후보 표면은 모두 skip한다.
8. click 직전과 Back 직전에 각각 fresh lease token + 180초 이상 idle 두 번 + 1초 증가 dwell을 새로 증명한다.
9. click 뒤 owner가 활동하면 Back도 하지 않고 `restore_pending=true`로 남긴다. history mismatch에는 goto fallback·retry가 없다.
10. 성공은 같은 target에서 목적 URL·인증을 확인하고 `Page.getNavigationHistory`의 직전 entry를 `Page.navigateToHistoryEntry`로 복원한 뒤 exact 원 URL·인증을 다시 증명한 때만 기록한다.
11. 종료는 WebSocket disconnect뿐이다. 사람 창·탭·브라우저·프로필·세션을 닫거나 삭제하지 않는다.
12. canonical, 저장소 Claude mirror, 사용자 Claude/Codex/Hermes 설치 tree는 모든 파일이 byte-identical하다.

## RED 인수 테스트

- macOS locator가 다른 PID를 배제하고 bounds/title이 유일한 창만 선택하며, 모호/권한실패 때 focus/capture 0회인지 검증한다.
- 캡처 명령이 exact `screencapture -x -l <CGWindowID>`이고 0700 임시폴더·0600 파일·즉시 삭제 계약인지 검증한다.
- 다중 endpoint/target 환경에서 지정 관리 endpoint의 exact target만 attach하고 substring/첫 탭 fallback이 없는지 검증한다.
- 가짜 시각이 900초를 넘어도 `HUMAN_AUTH`가 timeout되지 않고 auth + 15초 quiet까지 기다리는지 검증한다.
- `HUMAN_AUTH` 동안 반복 focus/navigate/click/type/submit/close가 모두 0인지 검증한다.
- keepalive가 click 1회 → 목적지/auth 검증 → history 조회 → previous entry Back 1회 → 원 URL/auth 검증 순서인지 검증한다.
- 두 번째 mutation gate 실패 또는 owner activity 발생 시 Back 0회와 `restore_pending`인지 검증한다.
- dirty/shared/unverified/paid/new/target_blank/download/다른 origin이면 mutation 0회인지 검증한다.
- unrelated-domain cookie를 인증 근거로 보지 않고 plaintext cookie를 저장하지 않는지 검증한다.
- installer가 nested Swift asset까지 재귀 설치하고 canonical/mirror/세 설치본 전체 tree가 동일한지 검증한다.

## 배송 게이트

- RED 커밋 → 최소 구현 GREEN → focused tests → 적대 검증(V1) → `./verify.sh` → 실제 macOS Swift 열거/창별 캡처 smoke(브라우저 mutation 없음) → 설치본 해시 비교 → PR/CI/merge → ledger GREEN.
- 라이브 keepalive mutation은 테스트 fake와 headful test fixture에서만 검증한다. 사용자의 실제 채용사이트 탭에는 이 코드 변경 작업 중 mutation을 실행하지 않는다.

