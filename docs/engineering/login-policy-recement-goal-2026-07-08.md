# Goal — 로그인 정책 SOT 재확인 + 2FA 브라우저 앞으로 + 메일 발송 정책 (2026-07-08)

모드: mixed(SOT 문서 + 코드) · 위험등급: L3(로그인 SOT 불변식·보안 경계·"코드 삭제" 지시)

## 현재 상태 (직접 연 file:line — 추측 금지)
- `docs/sot/26-portal-login-spec.json:19` INV1 = "3사 자동 로그인을 막지 않는다. 세션 만료 시 저장된 자격증명으로 자동 재로그인." (이미 존재)
- `:20` INV2 = "3사 모두 자동 로그인. 캡차·2FA·봇차단·멀티세션 락 감지 시에만 STOP."
- `tools/multi_position_sourcing/portal_login.py:339-341` 주석 "never re-disable LinkedIn here. A captcha/2FA/checkpoint is never bypassed" — **자동로그인 차단 코드는 이미 제거된 상태.**
- 차단 재유입 가드 테스트: `tests/test_multi_position_sourcing.py:2035,2040`("no constraint forbidding linkedin_rps auto_relogin"), `:4303`("assertNotIn linkedin_auto_login_disabled").
- `portal_login.py:235 _wait_for_human_intervention(page, channel, *, ready_check, options, note)` = **3사 2FA/챌린지의 단일 사람-게이트 관문**(399·423·454·478·506·540 6곳에서 호출). 메시지 출력 후 폴링·자동재개하나 **브라우저를 앞으로 띄우지 않는다**(bring_to_front 미사용 — grep 0건).

## 근본 원인 / 핵심 질문
사장님 지시 2건:
1. "로그인은 니가 무조건 한다"를 SOT에 다시 강하게 박고, **2FA 뜰 때만 사람이 하도록 브라우저를 위로 띄워라. 방해 코드는 삭제.**
2. "메일 발송하라고 하면 초안이 아니라 Send까지 눌러라"를 SOT에 박아라.

→ (1) 차단 코드는 실재하지 않음(정직 보고). 실제 신규 작업 = **2FA 관문에서 브라우저 앞으로 띄우기** + **SOT 불변식 문구 강화**. (2) = 메일 발송 정책 SOT 추가.

## 인수 기준 (기계 검사)
- AC1: `_wait_for_human_intervention` 진입 시 `page.bring_to_front()`가 호출된다(2FA 순간 브라우저 표면화). 실패해도 예외 전파 안 함(best-effort). → RED 테스트.
- AC2: `docs/sot/26-portal-login-spec.json` invariants에 (a) 자동로그인 무조건 수행·차단 금지 강화 문구, (b) "사람 개입(2FA 등) 필요 시 브라우저를 앞으로 띄운다" 신규 불변식이 존재. → JSON 로드 토큰 검사.
- AC3: 기존 가드 테스트(auto_relogin 비차단, linkedin_auto_login_disabled 부재) 여전히 GREEN.
- AC4(주관, 사람 판정): 메일 발송 정책이 CLAUDE.md/SOT에 명문화되되 SOT3(자율 후보 제안 발송 게이트)를 약화하지 않음 — "사장님 명시 지시 건에 한해 Send 실행".

## 적용 게이트
게이트 0(과거 회수 완료) → 0.5 워크트리(완료) → 1 스펙(본 문서) → 2 RED → 3 GREEN → 4 verify → 5 G/V1/V2 적대검증.

## 적대검증 정조준
- bring_to_front가 고아 아님: `_wait_for_human_intervention` 실제 호출 경로(6곳)로 배선됨을 grep 증명.
- best-effort try/except가 정상 흐름(폴링·자동재개)을 깨지 않는지.
- SOT 문구 강화가 기존 INV 번호/참조를 깨지 않는지.
- 메일 정책이 SOT3 후보 발송 게이트와 충돌·약화하지 않는지.

## 비범위
- OS 레벨 창 raise(osascript)는 best-effort 아님 — 다중 크롬 환경에서 위험, 이번엔 탭 bring_to_front만(문서에 한계 명시).
- Gmail 실제 Send 실행 배선: 현 세션 Gmail 도구는 create_draft만 제공 → 정책은 SOT에 박되, 발송 실행 경로는 send 가능한 도구/브라우저 클릭이 있을 때. 정직히 한계 명시.

## 적대 검증 로그
(G→V1→V2 후 채움)
