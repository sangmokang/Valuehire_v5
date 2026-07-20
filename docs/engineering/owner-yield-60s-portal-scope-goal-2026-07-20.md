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
- AC3: 판정 신호는 [앞창 앱 이름, OS idle, 크롬 활성 탭 URL]로 한정하며, URL 은 판정 순간 메모리에서 **호스트 추출에만** 쓰고 경로·쿼리·전체 URL 을 기록·로그·전송하지 않는다(스냅샷에는 호스트만 남김). 페이지 내용·키입력 비열람.

## 입력 영역 표 (결정성 규율 §1-11)

| # | 입력 상황 | 처리 |
|---|---|---|
| 1 | 앞창 ≠ Chrome (Slack·터미널·유튜브 앱 등) | portal_active=False → 양보 안 함 |
| 2 | 앞창 = Chrome, 활성 탭 호스트가 3사 도메인(서브도메인 포함) | portal_active=True → idle<60 양보, ≥60 재개 |
| 3 | 앞창 = Chrome, 활성 탭이 3사 아님(유튜브 등) | portal_active=False → 양보 안 함 |
| 4 | 앞창 = Chrome, 탭 URL 읽기 실패/창 0개/AppleScript 오류 | portal_active=None(불명) → idle<60 양보(최대 60초로 유계) |
| 5 | idle 읽기 실패(None) | fail-closed 양보(True) — 기존 유지 |
| 6 | 앞창 앱 이름 읽기 실패 | detector_unavailable → fail-closed 양보 — 기존 유지 |
| 7a | Windows(winpc) | GetLastInputInfo 기반 idle 단독 게이트(portal=None, 60초 유계). idle 판독 실패 → fail-closed 양보 |
| 7b | 그 외 OS(Linux 등, 함대에 없음) | unsupported_platform → fail-closed 양보 |
| 8 | idle == 60.0 경계 | 재개(>= 기존 규약 유지) |
| 9 | URL 이 `linkedin.com` 유사 위장 호스트(예: `evilinkedin.com`) | 도메인 정확 매칭(`==` 또는 `.suffix`)으로 3사 아님 → 양보 안 함 |
| 11 | 앞창 크롬 PID 에 CDP 포트 있음(사장님 9222·자동화 9223~9225) | 그 포트 /json/list 첫 page 탭 호스트로 판정(인스턴스 1:1 결합) |
| 12 | 앞창 크롬에 CDP 포트 없음 + 크롬 루트 프로세스 2개+ | AppleScript 응답 인스턴스 보장 불가 → portal=None(60초 유계, False 확정 금지) |
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

### V1 (Codex Rescue, fresh read-only, 2026-07-21) — verdict=FAIL → 결함 수정 후 재검증 요청
- HIGH portal_worker.py:917 실조작 장벽 180초 잔존 + portal 축 미반영 → **수정**: threshold 를 owner_activity 단일 출처(60)로, 비포털 확정은 idle 최소치·증가요건 면제. 회귀 테스트 MutationBarrierPortalScopeTests.
- HIGH owner_activity subprocess timeout 부재(hang 시 60초 유계 불성립) → **수정**: DETECTOR_SUBPROCESS_TIMEOUT_SECONDS=5.0. 회귀 테스트 DetectorTimeoutTests.
- MED javascript:/file: 스킴 오판·후행점 호스트 오판 → **수정**: http(s)만 확정, 호스트 후행점 정규화. 회귀 테스트 UrlSchemeAndHostNormalizationTests.
- MED 계약 activity_signal=macos_os_idle_only 충돌 → **수정**: 복합 신호명으로 갱신(+.claude 미러).
- MED AC3 문구-구현 불일치(전체 URL 이 파서에 전달) → **수정**: AC3 를 '판정 순간 메모리 호스트 추출만, 기록·로그·전송 금지'로 정정(호스트 추출은 URL 문자열 없이는 불가능).
- HIGH fleet_worker default_owner_probe 비-macOS None → **보류(기존 의도 결정)**: winpc 는 감지기 미구현이라 fail-closed 시 영구 정지 → INV9 자동 재개 우선의 기존 명시 결정(docstring). Windows 감지기는 후속 이슈로 유지.
- MED 사용자 크롬 vs 자동화 크롬(9223/9225) 인스턴스 구분 불가 → **수용(유계)**: 앞창 앱 이름 기반 한계. 오판 방향은 최대 60초 대기(안전측). PID/user-data-dir 결합 감지는 후속 이슈.
- MED 기존 장벽 테스트가 200/201초만 사용해 180 잔존을 미검출 → **수정**: 61초+portal 축 테스트 추가(위 MutationBarrierPortalScopeTests).

### V1 2차 (Codex Rescue, 2026-07-21) — verdict=FAIL → 격상 2건 실수정 + LOW 2건 정리
- 1차 수정 6건은 전부 "안 깨짐" 확인(장벽 60초·portal 축, timeout 5초 실측, 스킴/후행점, 계약, AC3, 회귀 테스트).
- HIGH(격상) 비-macOS probe None = 게이트 완전 우회 → **수정**: Windows 는 GetLastInputInfo idle 단독 게이트(portal=None, 60초 유계)로 default_owner_probe 활성. 회귀 WindowsIdleGateTests.
- MED(격상) 크롬 다중 인스턴스에서 잘못된 인스턴스 URL 로 portal=False 오판(즉시 진행 방향) → **수정**: 앞창 PID 의 CDP 포트(사장님 9222 포함)로 그 인스턴스 탭을 직접 읽어 1:1 결합, 포트 없고 루트 2개+면 None(False 확정 금지). 회귀 ChromeInstanceBindingTests.
- LOW fleet_worker 180/3분 잔존 주석 → 60/1분으로 정리. LOW goal EOF 공백 → 제거.
