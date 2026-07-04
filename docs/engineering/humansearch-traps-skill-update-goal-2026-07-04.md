# humansearch 실행 함정 5건 SKILL 명문화 — goal (2026-07-04)

## 현재 상태 (실측 근거)
2026-07-04 여기어때 Privacy Team Leader humansearch 런(LinkedIn RPS 55명 + 잡코리아 40명 + 갭 재검색)에서
아래 함정을 실측으로 확인했으나 `skills/humansearch/SKILL.md` "실행 함정" 절에 없었다:
1. 포털 디버그 크롬 포트 — 9222 아님, `scripts/portal_browsers.sh`(9223/9224/9225). health 로그인 판정은 URL 휴리스틱이라 오판(링크드인 login-cap 실측·잡코리아 `C_Frame_LoginCheck` false 실측).
2. 잡코리아 학교명 = base64 PNG 이미지(`.education .name img`) — innerText 추출 불가, 저장 후 LLM 판독으로 보정.
3. 잡코리아 경력 리스트+경력기술서 기간 중복 → dedupe 없으면 frequent_job_change 오탐(최OO 사례: 11개월 이직 1회가 2회로 집계).
4. RPS 키워드 검색이 CDP 실좌표 클릭+insertText 조합으로 실행됨 — 기존 메모리 "raw CDP 합성입력 안 됨"은 JS 합성 이벤트 한정으로 정정. 단 새 검색은 필터 미계승.
5. `raw_cdp.tab.close()` 는 ws만 닫음 — 탭 잔존(9225에 순회 탭 누적 실측).

## 근본 원인
런마다 재발견하는 비용 — 스킬 SOT(실행 함정 절)에 명문화되지 않아 다음 세션이 같은 시행착오를 반복.

## 인수 기준
- [기계] `skills/humansearch/SKILL.md` 에 위 5건이 "실행 함정" 절에 존재 (`grep -c "2026-07-04"` ≥ 4).
- [기계] `make red-ledger` 통과(기존 테스트 무손상 — 문서만 변경).
- [주관] 각 항목에 증상→원인→행동이 1항목 1블록으로 들어감.

## 비범위
humansearch.config.json 상수 변경, 러너 코드 변경, RPS 필터 패널 자동화 확립(미해결로 명시).

## 적대 검증 로그
- V1(자가): 문서-실측 대조 — 5건 모두 이 세션 실행 로그·DOM 덤프에 근거(추측 0). diff 는 "실행 함정" 절 추가만, 기존 절 약화 없음.
