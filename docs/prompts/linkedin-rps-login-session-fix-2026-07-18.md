# 프롬프트 — LinkedIn RPS 로그인·세션 문제 해결 (humansearch/aisearch 공용)

- 작성: 2026-07-18. 증상: humansearch 라이브 순회 시 LinkedIn Recruiter를 자동화로 못 몬다.
- 목적: 이 문제를 매번 겪지 않도록 원인·해결 절차를 못박는다(구현 워커·다음 세션이 그대로 따른다).

## 문제의 정체 (실측)

세 가지가 동시에 얽혀 있다:

1. **LinkedIn Recruiter는 좌석 1개 = 세션 1개만 허용.** 자동화가 새 탭/새 크롬으로 LinkedIn을 열면
   사장님이 쓰던 세션과 충돌 → "We have detected multiple sign-ins. Only one session is allowed"
   화면이 뜨고, 하나를 로그아웃해야 한다(다른 하나 강제 종료). 실측 2026-07-18.
2. **메인 크롬(사장님이 로그인한 곳)은 CDP 디버그 포트가 없다.** 그래서 정본 드라이버
   (`raw_cdp` + `humansearch_cdp_run.py`)로 못 붙는다. 확장(claude-in-chrome)으로는 붙지만
   새 탭 = 새 세션 → 위 1번 충돌.
3. **디버그 크롬(9225, `portal_browsers.sh start linkedin`)은 LinkedIn이 Cloudflare로 봇차단**한다
   ("Attention Required! | Cloudflare"). 자동화 프로필이 플래그돼 있어 자동 네비게이션이 막힌다.
   → 사람이 그 창에서 직접 Cloudflare 통과 + 로그인하면 세션이 유효해지고, 그 뒤 raw_cdp로 몰 수 있다.

## 해결 절차 (정본 — 이대로 한다)

**목표 상태: LinkedIn 세션이 오직 "자동화가 CDP로 붙을 수 있는 크롬" 한 곳에만 살아있게 만든다.**

1. **다른 LinkedIn 세션을 모두 닫는다.** 사장님이 메인 크롬에서 열어둔 LinkedIn Recruiter 탭을
   닫는다(좌석 1개라 이게 살아있으면 계속 충돌). 확장이 연 탭도 닫는다.
2. **자동화용 디버그 크롬을 띄워 맨 앞으로.** `./scripts/portal_browsers.sh start linkedin`
   (포트 9225, 프로필 `~/.valuehire/cdp_profiles/linkedin`). 탭이 0개면 CDP로 새 탭 생성:
   `curl -s -X PUT "http://127.0.0.1:9225/json/new?https://www.linkedin.com/talent"`.
   raw_cdp `attach(badge=True)` + `Page.bringToFront` + macOS `osascript ... to activate`로 앞으로.
3. **사람이 그 9225 창에서 직접 로그인 + Cloudflare 통과.** 자동화는 Cloudflare/2FA/보안확인을 대신
   누르지 않는다(SOT26 INV1·INV6, humansearch 안전 불변식). 사장님이 그 창에서 사람으로 통과시킨다.
   통과 후 recruiterSearch URL이 정상 로드되면 준비 완료.
4. **그때부터 자동화는 raw_cdp로만 9225를 몬다.** `CDP_HTTP=http://127.0.0.1:9225`,
   `VH_BUSY_AGENT=Claude`·`VH_BUSY_TASK=/humansearch` 배지 켜고, 순회 전 `Page.bringToFront` +
   `Emulation.setFocusEmulationEnabled`(백그라운드 탭=카드 0 렌더 함정 회피, SKILL 실행함정).
5. **재발 방지(선택, 근본):** 9225 프로필이 Cloudflare에 계속 걸리면, 사장님이 평소 쓰는 실제
   크롬 프로필을 `--remote-debugging-port=9225 --user-data-dir=<그 프로필>`로 한 번 띄워
   (사람 세션 그대로 CDP 노출) 자동화가 붙게 한다. 단 그 크롬으로는 사장님이 동시에 LinkedIn을
   다른 창에서 열지 않는다(좌석 1개).

## 왜 이렇게 (원칙)

- 자동화는 로그인·캡차·Cloudflare를 사람 대신 통과하지 않는다(계정 잠금·SOT 위반). 사람 게이트.
- 세션은 "자동화가 CDP로 붙을 수 있는 단 하나의 크롬"에만 둔다 — 좌석 1개 충돌을 구조적으로 없앤다.
- 확장(claude-in-chrome)은 폴백이며, 새 탭=새 세션 부작용이 있어 LinkedIn 대량 순회엔 raw_cdp를 쓴다.

## 체크리스트
- [ ] 다른 LinkedIn 세션 0개(메인 크롬 탭·확장 탭 닫음)
- [ ] 9225 디버그 크롬 앞으로 + 로그인 탭
- [ ] 사람이 9225에서 로그인 + Cloudflare 통과, recruiterSearch 정상 로드
- [ ] 자동화 raw_cdp(9225)로 bringToFront + focusEmulation 후 순회
- [ ] 사람인/잡코리아는 이미 9223/9224에 로그인돼 있어 좌석 충돌 없음(병렬 가능)
