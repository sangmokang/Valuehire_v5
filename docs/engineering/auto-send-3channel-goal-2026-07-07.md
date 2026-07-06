# Goal — 3사(사람인·잡코리아·링크드인) 제안 자동발송 v1 (2026-07-07)

- 모드: mixed (가능성 검토 noncode + 기능 구현 code-change)
- 위험등급: **L3** (외부 발송·되돌리기 불가·SOT 불변식 개정)
- 지시 근거: 사장님 명시 지시(2026-07-07 세션) — "사람인 잡코리아, 링크드인 세곳에서 모두
  자동발송을 하도록 기능 구현해줘." + 골든샘플 학습 지시(LinkedIn 인박스 실발송본).

## 현재 상태 (직접 확인한 사실)

- 발송 버튼을 실제로 누르는 코드는 레포 전체에 **0줄**. 오히려 3중 봉인:
  - 규칙: `CLAUDE.md:31` SOT 불변식 3("보내기는 항상 사람이 누른다"),
    `docs/sot/22-talent-search-filters.md:45`, `docs/sot/24-position-jd-sot.json:14`,
    `docs/sot/25-ai-search-execution-process.md:37`(INV3), `docs/sot/26-portal-login-spec.json:22`(INV4)
  - 코드: `tools/multi_position_sourcing/selectors.py:61`(forbidden 셀렉터),
    `tools/multi_position_sourcing/keywords.py:81`(`allow_inmail_send: False`)
  - 테스트: `tests/test_position_registration.py:766`(발송 심볼 봉인 — 단 position_registration 모듈 한정)
- 발송 직전 단계는 이미 코드화 완료(재사용):
  - 본문 조립: `tools/multi_position_sourcing/jd_outreach.py` `build_linkedin_inmail_jd`(골든샘플 v2)
  - 기계 검문: `tools/multi_position_sourcing/inmail_precheck.py`(채널 캡 1,899/2,000자·금지워딩)
  - CDP: `tools/multi_position_sourcing/raw_cdp.py`(CDPTab), 포트 사람인9223/잡코리아9224/링크드인9225
- 발송 절차(버튼 위치·주입 방식)는 전역 스킬 문서에만 존재(사람인 R18 fullClick §10.3~10.5,
  잡코리아 §16 제안보내기, LinkedIn 컴포저) — 재현 가능한 코드 없음.
- 골든샘플 실발송본 학습 완료: LinkedIn 인박스 2026-07-02 발송분(뤼튼 AX Backend Engineer,
  김현균님) → `skills/humansearch/references/inmail-sent-sample-2026-07-02.md` 로 보존.
  구조는 레포 골든샘플 v2(`skills/humansearch/references/inmail-golden-sample.md`)와 합치.

## 핵심 질문 / 근본 원인

자동발송이 "없는" 게 아니라 "금지로 봉인"돼 있었음. 사장님 명시 지시로 봉인을
**조건부 개정**한다 — 무조건 자동이 아니라, 기계 게이트를 전부 통과한 발송만 자동.

## 계약 (SDD — 입출력 먼저)

새 SOT: `docs/sot/28-auto-send-policy.json`
```json
{
  "sot": 28, "version": 1,
  "approved_by": "사장님 명시 지시 2026-07-07",
  "kill_switch_env": "VALUEHIRE_SEND_KILL_SWITCH",
  "dry_run_default": true,
  "dedupe_window_days": 90,
  "gate": { "min_score": 85, "require_precheck_pass": true, "hard_exclusions_block": true },
  "channels": {
    "saramin":      { "enabled": true, "daily_cap": 20 },
    "jobkorea":     { "enabled": true, "daily_cap": 20 },
    "linkedin_rps": { "enabled": true, "daily_cap": 15 }
  }
}
```

새 모듈: `tools/multi_position_sourcing/auto_send.py`
```
SendRequest(candidate_key, candidate_name, channel, position_id, body,
            score, score_breakdown?, hard_exclude_flags=(), precheck_passed=False)
evaluate_send(request, policy, ledger, env?, now?) -> SendDecision(allowed, reasons)
SendLedger(path): append / records / sent_count_on(channel, date) / already_sent(key, channel, window_days)
plan_send_steps(channel) -> (SendStep(action, site, selector_purpose), ...)
load_policy(path?) -> dict  # 스키마 fail-closed 검증
```
차단 사유 코드(전부 fail-closed): kill_switch_on, channel_unknown, channel_disabled,
score_missing, score_below_min, hard_excluded:<flag>, precheck_not_passed,
body_over_cap, duplicate_send, daily_cap_reached.

실행기: `tools/multi_position_sourcing/auto_send_runner.py`
— 기본 dry-run(브라우저 무접촉·계획만 출력), `--live` 일 때만 CDP 실행+원장 기록.

## 인수 기준

기계 판정:
1. `./verify.sh` exit 0 (기존 검사 전부 유지 + 신규 `tests/test_auto_send.py` GREEN).
2. 게이트가 fail-closed: 점수 없음/84점/하드제외/캡 초과/중복/일일 상한/킬스위치 → 전부 차단.
3. 배선(고아 0): `plan_send_steps` 가 `selectors.py` 의 실제 셀렉터 purpose 를 참조하고,
   runner 가 `evaluate_send`→`plan_send_steps`→원장 기록을 호출(grep 증명).
4. CLAUDE.md 불변식 3이 SOT28 참조로 개정되고 번호 불변식 5개 유지
   (`tests/test_sot_distrust_doublecheck_doc.py` GREEN 유지).

주관 판정(수동):
5. `--live` 실발송 1건 검증은 실제 후보·크레딧을 소모하므로 **다음 실전 턴에서 수행**
   — 이 goal 문서와 verdict 에 "라이브 수동 판정 필요"로 남긴다.

## 적대검증 정조준 항목

- 게이트 우회 경로: runner 가 evaluate_send 없이 클릭 가능한가? (금지 — 코드 경로 단일화)
- 원장 시간 조작: sent_count_on 이 dry-run 을 발송으로 세는가? (dry-run 은 카운트 제외)
- 중복 창(window) 경계: 90일째/91일째 off-by-one.
- 정책 파일 누락/오염 시 기본 허용으로 열리는가? (fail-closed 필수)
- 킬스위치 env 빈 문자열/"0" 처리.

## 비범위

- 발송 성공 후처리(Discord 알림·칸반 INSERT·candidate_activity_log) — 후속 작업.
- v4 orchestrator(propose 스캐폴드) 배선 — v4 코드 비의존 원칙 유지.
- Gmail/이메일 채널 — 이번 지시는 3사(사람인·잡코리아·링크드인).
- InMail 크레딧 잔량·24시간 재접촉 잠금의 기계 판정 — 후속.

## SOT 개정 명세 (사장님 지시로 유일하게 약화 허용된 지점)

- `CLAUDE.md` 불변식 3 → "SOT28 게이트 전부 통과 시에만 자동 발송, 그 외는 사람 손" 으로 개정.
- 하위 SOT(22/24/25/26)의 INV3·INV4 선언은 SOT28 이 조건부로 supersede 함을
  SOT28 본문에 명시(하위 문서 전면 수정은 후속 — 충돌 시 CLAUDE.md·SOT28 우선).
- `scripts/portal_browsers.sh` 안전규칙 주석 갱신.

## 적대 검증 로그

(작업 후 기록)
