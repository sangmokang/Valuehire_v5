# Portal Live-Search Runbook (Playwright, human-in-the-loop) — 2026-06-15

브라우저 제어 표준은 **Playwright**다 (Claude-in-Chrome은 맥북↔맥미니 소유권 문제로 미사용). 검색·수집까지만 하며 외부 발송은 하지 않는다. 캡차/2FA/보안문자는 절대 우회하지 않는다.

## 환경
- venv: `.venv-playwright` (python3.13 + `playwright==1.60.0`, chromium-1223 캐시)
- 실행 시 `PYTHONPATH=.` 필요
- 자격증명: `.env.local`(SARAMIN/JOBKOREA) → Keychain 시드:
  ```bash
  .venv-playwright/bin/python -m tools.multi_position_sourcing.portal_live_check \
    --env-file .env.local init-portal-credentials --channels saramin,jobkorea
  ```

## 로그인 프로필 저장·재사용 (영속)
로그인은 디스크 프로필에 저장되어 **다음 실행에서 자동 재사용**된다 (세션 만료 전까지 재로그인 불필요).
| 채널 | 프로필 경로 | 방식 |
| --- | --- | --- |
| 사람인 | `~/.valuehire/portal_profiles/saramin/default` | `launch_persistent_context` |
| 잡코리아 | `~/.valuehire/portal_profiles/jobkorea/default` | `launch_persistent_context` |
| LinkedIn | `~/.valuehire/cdp_profiles/linkedin` | 디버그 Chrome `--user-data-dir` (CDP) |

> 이 폴더들은 artifacts 밖에 있어야 하며 지우면 재로그인이 필요하다. 같은 프로필 폴더를 두 프로세스가 동시에 열면 안 된다(Playwright lock).

## 운영 원칙 (사장님 지시)
1. **자동 로그인 시도가 기본** → 막히면 사장님이 그 창에서 **직접 로그인(더 빠름)**.
2. 창은 **닫지 말고 프로세스로 유지**(`--hold`)해 세션을 살려둔다.
3. 중간 팝업은 **무조건 X로 닫고** 검색화면 진입(`_close_popups`).
4. 3채널 **병렬 실행**.

## 실행 — 사람인 / 잡코리아 (독립 persistent 창)
```bash
PYTHONPATH=. .venv-playwright/bin/python scripts/run_portal_search.py \
  --channel saramin --hold --wait-login-seconds 1800 \
  --keywords "스마트홈 영업" "조명제어 영업" ... --output artifacts/<job>_saramin.json
# jobkorea도 동일하게 --channel jobkorea
```

## 실행 — LinkedIn (CDP attach)
```bash
# 1) 디버그 Chrome 띄우기 (프로필 재사용)
CHROME="$HOME/Library/Caches/ms-playwright/chromium-1223/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"
"$CHROME" --remote-debugging-port=9222 --user-data-dir="$HOME/.valuehire/cdp_profiles/linkedin" \
  --no-first-run --no-default-browser-check "https://www.linkedin.com/talent/home" &
# 2) 로그인 확인 후 수집
PYTHONPATH=. .venv-playwright/bin/python scripts/collect_linkedin.py \
  --keywords "Crestron Korea" "Lutron Korea" ... --output artifacts/<job>_linkedin_cards.json
```

## 카드 수집 주의 (DOM)
- **LinkedIn 결과는 lazy-load** → 수집 전 **5초 대기 + 스크롤 5회** 필수. 셀렉터 `a[href*="/talent/profile/"]` 정상.
- 사람인/잡코리아 결과카드 셀렉터(`RESULT_CARD_SELECTORS`)는 라이브 DOM과 부분 불일치 → 보강 필요(별도 작업).
- `SearchLivenessMonitor`의 login_redirect 게이트는 사람이 막 로그인한 기업세션에서 오탐 → 대화형 러너에선 미사용, 실제 검색 입력창 존재로 readiness 판정.
