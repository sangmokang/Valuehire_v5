# Goal — 세션가드 코어 (session-guard-core)

- 작성: 2026-07-17 (/st 지시 5 — 직전 세션 session_guard/vault/cdp_util 아이디어를 v5 인프라 위에 재작성)
- 모드: code-change / 위험등급: L2 (순수 판정 모듈 + 스냅샷 파일, 네트워크·발송 없음)

## 현재 상태
- 사람인·잡코리아 서버세션(JSESSIONID·ASP.NET_SessionId)은 20~30분 유휴로 만료, LinkedIn li_at 는 장수명(SOT-28 §4).
- v5에는 세션 keepalive 판정·쿠키 스냅샷 계약이 없었다. 직전 세션이 별도 scripts/ 트리로 만들던 것을 폐기하고 v5 기존 인프라(raw_cdp·owner_activity·portal_keychain) 재사용으로 방향 전환.

## 핵심 계약 (스펙 먼저)
- 입력: `run_keepalive_once(site, owner_snapshot, tab_factory, last_at, now, snapshot_root)`
- 출력: `{"site", "at", "owner_active", "due", "action", "cookie_evidence"}` — action ∈ {skip_not_due, skip_owner_active, cookie_only_ok, probe_readonly, reauth, human_wait}
- 판정 우선순위(불변): ① owner_active(사람 점유) > ② due > ③ 쿠키 present(페이지 안 엶) > ④ unknown→읽기전용 probe > ⑤ absent→사람인·잡코리아 reauth / LinkedIn human_wait(자동 폼 로그인 금지, §3a·§5).
- 스냅샷: site별 최신 keep개 롤링, 파일 0600·디렉터리 0700, 내용·경로 로그 금지.

## 인수 기준
- [x] 기계: tests/test_session_guard.py 17개 GREEN, ./verify.sh exit 0 (실측 1682 passed).
- [x] 뮤턴트: owner 우선순위 제거 → 3 failed 감지 / classify 상수화 → 1 failed 감지 (적용→감지→원복).
- [ ] 4b: Codex Rescue 독립 반증 통과.

## 비범위 (정직한 한계)
- `fetch_cookies_via_cdp` 는 실크롬 왕복 검증 전 = **미검증** 표기. 실패 시 unknown→probe 폴백만 보장.
- 실제 keepalive 루프·재로그인 실행·러너 통합은 후속 조각(이 모듈은 판정·스냅샷 계약만). 엔트리는 CLI `python -m tools.multi_position_sourcing.session_guard --site <site>`.
- 스냅샷 파일명 정렬은 같은 자릿수 epoch(현행~2286년) 전제 — saved_at 기반 정렬은 후속 개선 후보.

## 적대 검증 로그
- G 자기반증: raw_cdp.attach(badge=False)·send(method) 시그니처 실존 대조(raw_cdp.py:124,202), owner_activity 계약 대조. 뮤턴트 2종 감지.
- V1(Codex): verdict.json 참조.
