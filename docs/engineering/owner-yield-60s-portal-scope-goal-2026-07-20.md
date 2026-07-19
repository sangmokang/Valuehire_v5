# owner-yield 60초 + 3사 포털 한정 판정 — goal (2026-07-20)

## 배경 (사장님 지시, 2026-07-20 CLI)

> "사람인·잡코리아·링크드인을 만질 때만 내가 개입하고 있는 걸로 하고, 3분이 너무 길으니 1분으로 바꿔라.
> 내가 상기 3개 사이트를 만지더라도 1분 뒤에는 니가 로그인해. 로그인의 우선순위는 매우 높다."

이 지시는 SOT29 INV9(2026-07-15, 180초·전 화면 양보)를 **개정**한다. 사장님 명시 지시 = 최상위.

## 현재 상태 (추측 아님, file:line)

- `tools/multi_position_sourcing/owner_activity.py:31` `DEFAULT_OWNER_IDLE_THRESHOLD_SECONDS = 180.0`
- `owner_activity.py:60` yield = `idle < threshold` — **무슨 화면을 쓰는지 무관**(유튜브 시청도 양보 유발)
- `tools/multi_position_sourcing/fleet_worker.py:58` `OWNER_YIELD_RESUME_SECONDS = 180`
- `docs/sot/29-fleet-control.md:45-49` INV9 = 180초, 전 화면
- `skills/login/SKILL.md` HUMAN_ACTIVE/장벽/반례 표의 180초 다수, `browser-control-contract.json:19,66` 180
- 근본 원인: 점유 신호가 "OS 입력 idle" 하나뿐이라 포털과 무관한 사용(유튜브)도 양보로 판정.

## 인수 기준 (EARS)

- AC1: WHEN 사장님이 크롬이 아닌 앱을 앞창으로 쓰거나, 크롬 활성 탭이 3사(saramin.co.kr·jobkorea.co.kr·linkedin.com) 도메인이 아닐 때, THE 워커 SHALL idle 값과 무관하게 양보하지 않는다(즉시 진행).
  - 검증: `python3 -m pytest tests/test_owner_yield_60s_portal_scope.py -q`
  - counter-AC: 크롬 활성 탭이 3사 도메인이고 idle<60 이면 반드시 양보한다.
- AC2: WHEN 크롬 활성 탭이 3사 도메인이고 마지막 입력 후 60초가 지나면, THE 워커 SHALL 자동 재개(로그인 포함)한다. 임계값 단일 출처 60.0/60.
- AC3: 판정 신호 읽기는 [앞창 앱 이름, OS idle, 크롬 활성 탭 URL의 **호스트만**]으로 한정한다(페이지 내용·키입력·전체 URL 경로 비열람·비기록).

## 입력 영역 표 (결정성 규율 §1-11)

| # | 입력 상황 | 처리 |
|---|---|---|
| 1 | 앞창 ≠ Chrome (Slack·터미널·유튜브 앱 등) | portal_active=False → 양보 안 함 |
| 2 | 앞창 = Chrome, 활성 탭 호스트가 3사 도메인(서브도메인 포함) | portal_active=True → idle<60 양보, ≥60 재개 |
| 3 | 앞창 = Chrome, 활성 탭이 3사 아님(유튜브 등) | portal_active=False → 양보 안 함 |
| 4 | 앞창 = Chrome, 탭 URL 읽기 실패/창 0개/AppleScript 오류 | portal_active=None(불명) → idle<60 양보(최대 60초로 유계) |
| 5 | idle 읽기 실패(None) | fail-closed 양보(True) — 기존 유지 |
| 6 | 앞창 앱 이름 읽기 실패 | detector_unavailable → fail-closed 양보 — 기존 유지 |
| 7 | 비 macOS | unsupported_platform → fail-closed 양보 — 기존 유지 |
| 8 | idle == 60.0 경계 | 재개(>= 기존 규약 유지) |
| 9 | URL 이 `linkedin.com` 유사 위장 호스트(예: `evilinkedin.com`) | 도메인 정확 매칭(`==` 또는 `.suffix`)으로 3사 아님 → 양보 안 함 |
| 10 | 그 외 전부 | fail-closed 양보(True) + detection_status 기록 |

## 결정 목록 (오너 확정 근거)

- 임계 60초: 사장님 지시 문면("1분").
- 3사 판정 = 크롬 활성 탭 호스트: 사장님 지시 문면("3개 사이트를 만질 때만"). 호스트만 읽고 전체 URL·내용은 비기록(SOT1 최소화 유지).
- URL 불명(표 4) = 60초 유계 양보: "로그인 우선순위 매우 높음" ↔ 안전(개입 중 앞지르기 금지)의 절충 — 최악 대기 60초.
- HUMAN_AUTH(2FA·캡차 사람 처리 중) 15초 정적 대기(session_guard:1503)는 이번 개정 비범위 — 로그인 인계 안전규약 유지.

## 게이트 계획

RED(새 테스트 커밋) → GREEN(최소 변경: owner_activity.py, fleet_worker.py 상수, 기존 테스트 스펙 갱신) → 문서 동PR(SOT29 INV9, skills/login SKILL.md+contract) → verify(pytest 전체) → 설치기 재실행(3 홈 동기화) → V1 Codex 적대검증.

## 비범위

- session_guard HUMAN_AUTH 정적 15초 · keepalive 주기(15/30분) · lock 규약 변경 없음.
- Hermes 경로 교정(별도 작업 #2).

## 재발 원장(R4) 관련

- 2026-07-20 사장님 신고: "유튜브 보는데 점유 판정" → 본 개정. 회귀 케이스 = 표 3.

## 적대 검증 로그

(후기록)
