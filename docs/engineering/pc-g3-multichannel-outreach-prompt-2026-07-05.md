# PC-G3 붙여넣기용 프롬프트 (사람인·잡코리아·Gmail 아웃리치 컴포저)

> 사장님 결정 반영(2026-07-05): 인재 제안 본문 구조 SSOT(4채널 공통 순서 — 개인화 인사 →
> 회사소개 → JD 원문 → 마무리/CTA)와 골든샘플 2건을 확정. 링크드인은 이미 끝남(PC-G2, PR#63)
> — 이 조각은 **같은 구조를 사람인·잡코리아·Gmail 채널 필드에 맞춰 쪼개 넣는 컴포저**를 추가한다.
>
> ⚠️ **v4 코드 절대 금지(CLAUDE.md·메모리 `ai-search-no-v4-code`)**: 사장님이 준 참고 SSOT 문서에
> 나오는 `tools/position-batch/lib/build-offer-bodies.mjs`·`saramin-bulk-register-from-jobkorea/register-batch.mjs`·
> `jobkorea-bulk-register/register-one.mjs` 는 **v4(Node/mjs) 경로다 — v5엔 없고, 절대 참고/이식 금지.**
> v5는 이미 Python으로 같은 골격을 갖고 있다: `tools/multi_position_sourcing/jd_outreach.py`
> (PC-G2 `build_linkedin_inmail_jd`) + `tools/multi_position_sourcing/inmail_precheck.py`
> (`BRIEFING_ELEMENT_KEYS` 8요소·`CHANNEL_CHAR_LIMITS`(linkedin_rps 1899/saramin 2000/jobkorea 2000)·
> `char_count`·금지워딩 린트). **이 조각은 v4 문서의 "구조"만 참고하고, 구현은 이 v5 모듈을 그대로
> 재사용(SOT5)한다.**

---

너는 Valuehire_v5 저장소(/Users/kangsangmo/Valuehire_v5)에서 일한다. 최상위 규칙은 CLAUDE.md(SOT)와 docs/harness.md(게이트)다. 사장님께 보고는 무조건 쉬운 한국어로.

[작업] 통합 파이프라인 백로그의 PC-G3 조각 중 **사람인 채널 1개**를 harness 게이트대로 구현한다. 한 조각 = 한 worktree = 인수기준 1개. 잡코리아·Gmail은 이 프롬프트를 재사용해 다음 조각으로 뒤에 이어간다(맨 아래 "다음 조각" 참고).

- 설계도: `docs/engineering/valuehire-pipeline-consolidation-backlog-2026-07-01.json` 의 `PC-G3`(depends_on `PC-G2`, 완료됨).
- 선행 참고(반드시 먼저 읽어라, SOT5 재사용 대상):
  - `tools/multi_position_sourcing/jd_outreach.py` — PC-G2 `build_linkedin_inmail_jd` 전체. `_clean_text`·`_bullets`·`_strip_invisible`·`_reject_control`·`_reject_reserved_header`·`_contains_unverified` 같은 방어 헬퍼가 이미 있다 — **복붙 재구현 금지, 그대로 import/재사용**(같은 파일이면 바로 호출 가능).
  - `tools/multi_position_sourcing/inmail_precheck.py` — `BRIEFING_ELEMENT_KEYS`(8요소: one_line·history·funding_stage·revenue·headcount·parent_group·ceo_quote·recent_news)·`CHANNEL_CHAR_LIMITS`(saramin=2000)·`char_count`·`precheck_inmail`.
  - `tests/test_linkedin_inmail_jd.py` — PC-G2 골든 픽스처·테스트 작성 패턴(oracle=`precheck_inmail`, AST로 부수효과 0 검사 등). 이번 조각도 동일 패턴을 따른다.
  - `skills/humansearch/references/inmail-golden-sample.md` — 골든샘플 v2(문체·금칙어 SOT).

[사장님이 준 인재 제안 본문 구조 SSOT — 4채널 공통 순서(고정)]
```
① 개인화 인사 (2~3줄) — 후보자 존중 + 왜 이 포지션을 제안하는지
② [회사소개] — 불릿("-"/"·" 시작, 서술 문단 금지). 8요소 중 확인된 것만, 없으면 그 줄 생략(환각 금지)
③ 채용 공고 원문(JD 그대로, 누락 금지) — 주요업무/자격요건/우대사항/근무조건/전형절차를 [헤더]+불릿
④ 마무리/CTA — R21 CTA(무료 이력서 피드백/커리어 검증) + 본 메일 회신 유도
⑤ 서명
```
사람인 채널 매핑(이번 조각 범위):
- **offerComment 칸** ← ①+②+포지션 셀링(짧게). 사람인 채널 한도 2,000자(`CHANNEL_CHAR_LIMITS["saramin"]`, SOT5 재사용).
- **chargeWork 칸** ← ③ JD 원문만(주요업무/자격요건/우대사항/근무조건/전형절차, `[헤더]`+"-" 불릿). 동일 한도 2,000자.
- ④·⑤(CTA·서명)는 offerComment 끝에 붙인다(사람인은 칸이 2개뿐이라 링크드인처럼 별도 섹션 없음 — PC-G2 의 `_VERIFIED_PULL`+`_CLOSING`+`_PS_CTA` 상수를 그대로 재사용).

[골든샘플 — 테스트 픽스처로 그대로 써라(사장님 확정, 실명·실회사라 테스트 안에만)]
1. 개인화 인사/오프너 톤 예시(사장님이 실제 보낸 문구, 레주메 확보형 — 참고용):
   > "안녕하세요 김홍교 CTO님, 테크 서치펌 밸류커넥트의 헤드헌터 강상모입니다. 수락해주셔서
   > 감사합니다. 혹시 갖고 계신 레쥬메가 있으시다면..."
   ⚠️ 이건 "레주메 확보"용 메시지라 이번 PC-G3(포지션 제안 컴포저)과 메시지 **유형이 다르다** —
   그대로 본문에 박지 말고, `_INTRO`(PC-G2에 이미 있는 "저는 테크 서치펌 밸류커넥트(Valueconnect)의
   헤드헌터 강상모라고 합니다.")와 톤이 일치하는지만 참고해라. 레주메 확보형 메시지 자체를 만들지
   여부는 범위 밖 — 필요하면 별도 조각으로 사장님께 여쭤라.
2. 회사 리서치 예시(테크핀레이팅스) — 이건 **8요소 브리핑을 만들기 위한 원본 리서치 자료의 분량감**
   참고용이다. 실제 `company_briefing` dict 값은 PC-G2와 동일하게 **한 줄짜리 불릿**으로 압축해서
   넣는다(스키마 변경 금지, 8키 그대로): 예) `one_line="신한은행·더존비즈온·SGI서울보증 3사 합작
   핀테크 — 국내 1호 기업금융 특화 CB 플랫폼 사업자"`, `headcount="약 50명(원티드 기준)"` 등.

[인수 기준 = 게이트1, 기계 검사]
신규 함수 `build_saramin_offer_body(*, candidate_name, personalized_opener, company_name, position_title, company_briefing, jd_responsibilities, jd_qualifications, jd_preferences, jd_conditions=None, hiring_process=None, language="ko") -> dict[str, str]`
(정확한 인자명은 `build_linkedin_inmail_jd`와 대칭을 우선하되, ③을 세분화하려면 `jd_preferences`(우대사항)·`jd_conditions`(근무조건)·`hiring_process`(전형절차) 를 선택 인자로 추가 — 없으면 해당 섹션 생략, 있으면 필수 섹션과 동일하게 검문).
반환값: `{"offer_comment": str, "charge_work": str}`.

- `offer_comment`: ①+②+짧은 포지션 셀링(1~2줄, position_title·company_name 포함) + ④CTA + ⑤서명. `assert_outreach_jd_within_cap(..., channel="saramin")` 통과(2,000자 이내).
- `charge_work`: ③만. `[주요 업무]`/`[자격 요건]`/`[우대 사항]` 헤더 + `_bullets()` 재사용 조립(우대사항 없으면 헤더 자체 생략, 빈 불릿 헤더 금지는 기존 `_bullets` fail-closed 그대로 상속). 동일 캡 검증.
- 두 칸 다 `_clean_text`/`_reject_control`/`_reject_reserved_header`/`_contains_unverified` 방어를 그대로 통과(PC-G2와 동일 공격 벡터 회귀 테스트: 미확인 마커·개행 주입·예약헤더 위장·제어문자).
- `company_briefing` 은 `BRIEFING_ELEMENT_KEYS` 8키 밖 거부(SOT5, PC-G2와 동일 assert).
- 부수효과 0 (AST import 검사로 파일 I/O·네트워크·Send류 호출 없음 확인 — PC-G2 테스트 패턴 재사용).
- (회귀) 기존 878개+ 테스트 전부 그대로 통과.
그리고 `./verify.sh` exit 0.

[절차 — 하나도 건너뛰지 말 것]
0. 게이트0 시작자격: `make red-ledger` 로 미해결 RED 없음 확인. 과거 회수: `git grep -n "build_saramin\|offer_comment\|charge_work\|saramin.*offer\|jd_outreach"` — 중복 구현 없는지, `jd_outreach.py`에 이미 뭔가 있는지 먼저 본다.
0.5 워크트리(필수): `git worktree add ../Valuehire_v5-saramin-offer-composer -b task/saramin-offer-composer`. 메인 작업트리 직접 수정 금지. `git worktree list` 로 다른 세션과 파일 충돌 없는지 확인(특히 `jd_outreach.py`/`inmail_precheck.py`를 다른 창이 만지고 있는지).
2. RED 먼저: `tests/test_linkedin_inmail_jd.py` 옆에 `tests/test_saramin_offer_body.py` 신설, 위 인수기준을 파라미터라이즈 실패 테스트로 먼저 커밋(ImportError).
3. 구현(RED→GREEN 최소 변경): `jd_outreach.py`에 `build_saramin_offer_body` 추가. 기존 헬퍼·상수(`_INTRO`·`_VERIFIED_PULL`·`_CLOSING`·`_PS_CTA`·`_clean_text`·`_bullets`) 재사용, 새 스키마·새 정규화 로직 금지(SOT5).
4. 검증: `./verify.sh` exit 0, 통과 숫자 그대로 보고.
5. 게이트4b 2패스 적대검증(SOT5): (1) 내가 먼저 스스로 깬다 — offer_comment/charge_work 각각 2,000자 초과 시 STOP 확인, 미확인 마커/개행/예약헤더 우회, `jd_preferences`/`jd_conditions` 없을 때 섹션 누락이 아니라 "생략"으로 정상 처리되는지, 브리핑 8키 밖 키 거부. (2) Codex Rescue 독립 2차 적대검증(RESCUE REQUEST 로 명시). 결과를 `docs/engineering/pc-g3-saramin-offer-composer.verdict.json` 에 축적.
6. 배송: `make ship` → PR. CI 초록 + merge 전엔 "완료" 없음. merge 후 red-ledger GREEN 마감 + 워크트리 정리.

[SOT 불변식 — 약화 금지] 제안/메일 "보내기" 자동클릭 금지(이 함수는 문자열만 만들고 저장/발송 안 함) · v4 코드 금지 · 회사 사실 환각 금지(출처 없으면 그 줄 생략) · 금지워딩(전화·통화 요청, 과장 "딱 맞") 금지 · external_posting_sent=False 유지.

끝나면 사장님께 쉬운 한국어로 "무엇을/왜/다음"만 보고.

---
## 다음 조각(이 프롬프트에서 채널만 바꿔 재사용)
- **PC-G3-잡코리아** — `build_jobkorea_offer_body(...) -> dict[str,str]`: `{"company_intro": ..., "responsibilities": ..., "qualifications": ..., "preferences": ...}` 4칸 분리. ⚠️ 잡코리아는 **이모지·"•"·화살표 금지**(인코딩 깨짐, SSOT 명시) — `[헤더]`+줄바꿈만, `_bullets()`의 "· " 불릿 기호를 그대로 쓰면 안 된다(잡코리아 전용 변형 필요, 이때도 새 정규화 로직 만들지 말고 `_clean_text` 등 문자 검문 헬퍼는 그대로 재사용하고 "표시 기호"만 바꿔라).
- **PC-G3-Gmail** — `build_gmail_offer_html(...) -> str`: HTML, 글자수 제한 없음(①~⑤ 전부, 링크드인과 제일 비슷 — `build_linkedin_inmail_jd` 골격에서 `assert_outreach_jd_within_cap` 채널 캡만 빼거나 매우 큰 한도로 대체). CTA 링크(`https://valuehire.cc/resume`)를 `<a href>`로 감싸는 것 외 신규 로직 최소화.
- **(범위 밖, 사장님 확인 필요)** "레주메 확보형" 메시지(위 골든샘플 1번, 포지션 제안이 아니라 이력서 자체를 요청하는 짧은 메시지) — 별도 메시지 유형으로 만들지, 만든다면 어느 채널에 붙일지 사장님께 먼저 물어라.
