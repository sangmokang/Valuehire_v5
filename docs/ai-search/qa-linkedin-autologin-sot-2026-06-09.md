# QA 이슈: LinkedIn 자동로그인 금지 revert (SOT 위반) — 전면 복구 + 로직 체크

- **등록일**: 2026-06-09 KST
- **심각도**: High (운영 자동화 차단 + 반복 시간/리소스 손해)
- **상태**: 해결 (전체 테스트 green, 294 tests)
- **SOT 불변식**: 사람인·잡코리아·**LinkedIn RPS** 3사 모두 시크릿 저장소(`.env.local` / `~/.secrets` / Mac Keychain) 자격증명으로 **자동 로그인**한다. 자동 로그인을 절대 막지 않는다. ([`docs/search-access.md`](../search-access.md) 참조)

## 증상
`tools/multi_position_sourcing` 포털 로직에서 LinkedIn RPS 자동 로그인을 막는 코드/스키마/테스트가 반복적으로 다시 들어옴("세션 재사용 전용 / human-login only / auto_login_disabled / auto_relogin 금지"). 사장님 명시 지시("절대로 자동 로그인을 막지 마")와 정면 충돌하며, 자동 소싱이 LinkedIn에서 멈춰 막대한 시간·리소스 손해 유발.

## 루트 원인
- 정책이 **여러 레이어에 중복 인코딩**돼 있어, 한 곳만 풀고 다른 곳을 놓치면 전체가 다시 "금지" 상태로 수렴. DB CHECK 제약 + 이벤트 스토어 가드 + DoD 감사 + 프리플라이트 + 복구 + 자격증명 키까지 LinkedIn 금지가 박혀 있었음.
- 작업 중 untracked 소스 파일(`portal_*`)이 외부(편집기/동시편집)에서 부분적으로 "금지" 상태로 되돌아가는 현상도 관측됨. → **`docs/search-access.md`를 SOT로 못박고** 그 기준으로 전 레이어를 일관화.

## 철저한 로직 체크 — LinkedIn 자동로그인을 막던 전체 지점 (모두 해제)
| # | 파일 | 위치 | 변경 |
|---|------|------|------|
| 1 | `access.py` | `PORTAL_CREDENTIAL_KEYS` | `linkedin_rps` 추가 (`LINKEDIN_USERNAME/PASSWORD`, `LINKEDIN_RPS_*` 폴백) |
| 2 | `access.py` | `resolve_portal_credentials`/`portal_credential_status` docstring | LinkedIn 제외 문구 제거 |
| 3 | `portal_autologin.py` | `LINKEDIN_RPS_LOGIN_URL`, `AUTO_LOGIN_SELECTORS`, `login_url_for_channel` | LinkedIn 로그인 URL·셀렉터·라우팅 추가 |
| 4 | `portal_recovery.py` | `MacKeychainPortalCredentialProvider.load/store` | `{saramin,jobkorea,linkedin_rps}` 허용 |
| 5 | `portal_recovery.py` | `recover_after_reauth` auto_relogin 분기 | linkedin_rps 포함 (실패 시 human/pause/alert 폴백 유지) |
| 6 | `portal_login.py` | `_auto_login_session` | LinkedIn `auto_login_disabled` 차단 블록 제거 |
| 7 | `portal_login.py` | `_linkedin_rps_session` | 기존세션 없으면 자동 로그인 시도 → 실패 시 human 폴백 |
| 8 | `portal_login.py` | `_linkedin_rps_ready` | URL만이 아니라 Recruiter 검색 마커로 로그인 판정 강화 |
| 9 | `portal_live_check.py` | `live_readiness_payload` | `linkedin_auto_login_disabled` 체크 제거, `linkedin_rps_keychain_credentials` 추가 |
| 10 | `portal_live_check.py` | `init_portal_credentials_payload` | LinkedIn skip 분기 제거, 기본 채널에 포함 |
| 11 | `portal_live_check.py` | `run_live_search` auto_relogin 게이트 | `PROTECTED_PORTAL_CHANNELS` 사용(linkedin 포함) |
| 12 | `portal_live_check.py` | DoD 감사 스키마 기대 리스트 | `reauth_events_no_linkedin_auto_relogin_check` 항목 제거 |
| 13 | `portal_ops.py` | `validate_reauth_event_policy` | linkedin auto_relogin 금지 raise 제거 |
| 14 | `portal_ops.py` | weekly-count row 검증 | linkedin auto_relogin "malformed" 처리 제거 |
| 15 | `portal_dod_audit.py` | `_weekly_counts_policy_issues`, 트렌드/스키마 row 검증, `_has_linkedin_reauth` | linkedin auto_relogin 금지 플래그 제거, reauth 관측은 auto_relogin/human 모두 인정 |
| 16 | `session-state-supabase-schema-2026-06-09.sql` | `reauth_events_no_linkedin_auto_relogin_check` | CHECK 제약 제거 |

## 직접 검색(요구사항 #2) — 함께 구현
- `models.CandidateResultCard` + `portal_worker.collect_result_cards` 추가 → 검색 실행 후 결과 카드 수집.
- `PortalSearchAttempt.candidate_cards` / `GuardedSearchResult.candidate_cards` / `safe_result_payload`의 `result_count`·`results`로 결과 반환 연결(프리플라이트에서 멈추지 않음).

## 변경 금지(안전 경계) — 유지 확인
- 캡차/2FA/보안문자/IP보안/checkpoint/이상접근: **자동 우회 안 함** → 감지 시 정지 + 사람 개입/Discord 알림 (`_has_security_challenge`, `auto_relogin_portal`가 챌린지 시 `False` 반환).
- 자격증명: 평문 금지, 시크릿 저장소(env/Keychain)에서만 로드.
- 외부 발송(후보 발송·InMail·이메일): 자동 금지, 기존 승인 게이트 유지(검색·수집까지만 자동).

## 회귀 방지
- SOT를 `docs/search-access.md` 상단 불변식 + 본 QA 문서 + 에이전트 영구 메모리(`never-block-portal-autologin`)에 3중 기록.
- 소스 주석에 `SOT invariant` 표기 — 다시 LinkedIn을 막으면 SOT 위반임을 코드에서 명시.
- 검증: `python3 -m unittest discover -s tests -p "test_*.py"` → 294 tests OK (3회 연속 green).
