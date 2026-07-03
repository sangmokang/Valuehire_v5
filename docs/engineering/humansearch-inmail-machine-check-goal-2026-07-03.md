# humansearch #8 InMail 발송 전 기계 체크리스트 — goal (2026-07-03, FULL)

사장님 지시(2026-07-03): /humansearch #8 "핵심 후보 개인화 InMail 문구"를 업그레이드하고,
Movensys 사고(2026-06-30, 수신자 Meseret Abayebas Tadese에게 "Rocha연구원님" 인사 + "하니다" 오타 +
VERIFIED-PULL·P.S. CTA 누락)가 **기계적으로 재발 불가능**하도록 발송 전 체크를 코드로 강제한다.

## ① 현재 상태 (증거)

- `skills/humansearch/SKILL.md:129-141` — #8 문구 구조·금지 워딩이 **산문 규칙**으로만 존재. 기계 검증 0.
- `skills/humansearch/references/inmail-golden-sample.md` (PR#47, main 086b4f1) — 구조/절대규칙은 있으나
  ① 발송 전 체크리스트 없음 ② 언어 자동 선택 규칙 없음 ③ 채널별 글자수 한도 없음 ④ 채널 경계 없음.
- 반면교사 라이브 증거: `~/.vh-search-results/linkedin_rps/2026-06-30/tot-physical-ai/results.json` 에
  "Meseret Abayebas Tadese" 실재(수확 name 필드) — 그런데 발송문 인사말은 "Rocha연구원님"이었다.
- 기존 판정 로직 단일 출처: `tools/multi_position_sourcing/humansearch.py` (채점·하드제외·URL 게이트).
  InMail 문구 검증 모듈은 부재.
- 관련 규칙 SOT: `~/.claude/skills/linkedin-rps-jd-set-builder/SKILL.md` R0/R2(1,899)/R20/R21/R25/R10·R24,
  `~/.claude/skills/position-register/SKILL.md` §1.5(회사 브리핑 8요소, 6개 미만 보고),
  사람인 offerComment·잡코리아 EXEC_WORK 한도 2,000자.

## ② 근본 원인

InMail 문구 품질 규칙이 전부 "사람(LLM)이 기억해서 지키는 규칙"이라, 세션이 다르거나 서두르면
이름 오기·오타·필수 문단 누락이 그대로 발송 직전 문구에 남는다. 검증이 코드 경계에 없다.

## ③ 인수 기준 (EARS + 검증 명령 + counter-AC)

공통 검증 명령: `./verify.sh` (tests/test_inmail_precheck.py 포함 전체)

- **AC1 이름 일치(STOP)** — If 문구 인사말에서 추출한 이름이 수확 프로필 이름과 부분 일치하지 않으면,
  then `precheck_inmail` 은 ok=False + `name_mismatch` STOP 을 반환해야 한다.
  - 검증: `pytest tests/test_inmail_precheck.py -k name -q`
  - counter-AC: 인사말 추출 실패(이름 못 찾음)를 "통과"로 처리하면 가짜(fail-open). 추출 실패도 STOP.
- **AC2 채널 글자수(STOP)** — While channel=linkedin_rps 일 때 NFC 문자수>1,899, 또는
  saramin/jobkorea 일 때 >2,000 이면, then STOP.
  - 검증: `pytest tests/test_inmail_precheck.py -k charlimit -q`
  - counter-AC: 바이트 길이/UTF-16 코드유닛으로 세어 경계(1899/1900)를 오판하면 가짜.
- **AC3 금지 워딩(STOP, CTA 오탐 금지)** — If 본문에 통화/전화 요청·"딱 맞/정확히 맞물/꼭 맞"류 과장·
  `{`/`}`·HTML 주석(`<!--`)이 있으면 then STOP. 단, R21 표준 CTA "딱 맞지 않으셔도"는 과장이 아니므로 통과.
  - 검증: `pytest tests/test_inmail_precheck.py -k forbidden -q`
  - counter-AC: R21 P.S. 문장까지 차단해 표준 CTA를 못 쓰게 되면 가짜(과잉 차단).
- **AC4 회사 브리핑 요소(보고)** — If 브리핑 요소(§1.5 8요소) 확인 개수<6 이면, then STOP이 아니라
  `briefing_below_6` **warning**(보고 후 진행)을 반환해야 한다.
  - 검증: `pytest tests/test_inmail_precheck.py -k briefing -q`
  - counter-AC: warning이 ok=False로 실행을 막으면 §1.5("보고 후 진행") 위반.
- **AC5 한글 자모 분리·기지 오타(STOP)** — If 본문에 한글 자모 단독 출현(`[ㄱ-ㅣ]`, 완성형 정상 문장엔 0회 —
  codex V1 LOW 지적으로 `{2,}`→단독으로 보수화 확정) 또는 알려진 오타("하니다")가 있으면 then STOP.
  - 검증: `pytest tests/test_inmail_precheck.py -k typo -q`
  - counter-AC: "합니다"·정상 문장을 오탐하면 가짜.
- **AC6 VERIFIED-PULL + P.S. CTA 필수(STOP)** — If 본문에 VERIFIED-PULL 마커(무료 이력서 피드백 문구)
  또는 P.S. 인입 CTA(R21, valuehire.cc)가 없으면 then STOP. (P.S. 검사는 codex V1 MED 지적으로 추가.)
  - 검증: `pytest tests/test_inmail_precheck.py -k verified -q`
  - counter-AC: 영어 본문(resume feedback)을 못 알아보고 STOP 내면 가짜(언어별 마커 필요).
- **AC7 언어 자동 선택** — Where 프로필 이름·이력이 영문이면 `body_language_for_profile` 은 "en",
  한국어 프로필이면 "ko" 를 반환해야 한다.
  - 검증: `pytest tests/test_inmail_precheck.py -k language -q`
  - counter-AC: 빈 이름에서 예외를 던지거나 기본값 없이 crash 하면 가짜.
- **AC8 문서 배선(가드)** — SKILL.md #8 과 골든샘플이 기계 체크리스트·CLI 호출(`inmail_precheck`)·
  언어 규칙·채널별 한도·채널 경계를 명시해야 한다(문서 가드 테스트).
  - 검증: `pytest tests/test_inmail_precheck.py -k docguard -q`
  - counter-AC: 모듈만 만들고 SKILL이 호출을 명시하지 않으면 고아 = 가짜 완료.

## ④ Harness 게이트 계획

0 red-ledger(완료: bool-query PARKED) → 1 본 goal → 2 워크트리 `worktrees` ../Valuehire_v5-humansearch-inmail-machine-check
(branch task/humansearch-inmail-machine-check)에 RED 커밋 → 3 최소 구현(`tools/multi_position_sourcing/inmail_precheck.py`
+ SKILL/골든샘플 개정) → 3.5 배선 증명(SKILL #8 → CLI 명령 그대로 실행한 라이브 1건) → 4 `make verify` 숫자 그대로 →
5 `make ship` → PR → merge → 6 /clear.

## ⑤ codex 적대검증 정조준

- 인사말 추출 fail-open(이름 못 찾으면 통과?) / 조사·호칭 변형("Rocha연구원님", "Hi Meseret,") 우회
- 글자수 경계(1899 vs 1900, NFC/NFD, 이모지·서로게이트)
- 금지 워딩 우회(공백 삽입 "딱  맞", 전각, zero-width) 및 CTA 오탐
- 자모 검사 오탐(정상 한글) / "하니다" 부분 문자열 오탐 가능성
- SKILL 문서와 모듈 동작의 불일치(문서가 약속한 체크가 코드에 없음)

## ⑥ SOT 체크리스트

- 읽음: 루트 `CLAUDE.md`, `docs/harness.md`(게이트), `skills/humansearch/SKILL.md`(H-SOT),
  `skills/humansearch/references/inmail-golden-sample.md`, linkedin-rps-jd-set-builder·position-register §1.5·
  saramin/jobkorea sourcing·pos-fill·position §1.5 라우팅.
- SOT 수정: 예 — `skills/humansearch/SKILL.md` #8 + `references/inmail-golden-sample.md` 를 같은 PR에서 개정
  (코드와 문서 동시 변경 = 드리프트 차단).

## ⑦ 비범위

- InMail 자동 발송(SOT3 — 영원히 비범위), 컴포저 라이브 자동 입력 개선(기존 실행 함정 절 유지),
- 범용 한국어 맞춤법 검사기(기지 오타 목록 + 자모 분리만), 대량 템플릿 저장(=linkedin-rps-jd-set-builder),
- 사람인·잡코리아 포지션 등록(=position-register).

## ⑧ 롤백 절차 (FULL)

merge 후 문제 시: `git revert <squash-commit>` 1커밋 — 신설 모듈·테스트·문서 개정이 한 PR이므로
revert 하나로 이전 골든샘플(086b4f1) 상태로 복원된다. 런타임 데몬·DB 변경 없음.

## ⑨ 영향 반경 (FULL)

- 이 변경이 깨지면: humansearch #8 문구 검증 CLI가 오작동(과잉 STOP=문구 제공 지연 / fail-open=결함 문구 통과).
  발송 자체는 항상 사장님 수동(SOT3)이라 오발송 위험은 없음. PII: 프로필 이름을 로컬 검증에만 사용, 외부 전송 없음.
- 기존 humansearch 채점·등록 경로는 import 하지 않으므로(신규 모듈 단방향 의존) 회귀 반경 없음.

## 적대 검증 로그

### codex 1차 (V1) — VERDICT: FAIL → 전량 수정
- agentId `ad9aad299c3012877`, transcript output:
  `/private/tmp/claude-501/-Users-kangsangmo-Valuehire-v5/e5873c35-1aa1-4c68-a0a2-7bbd363669fe/tasks/ad9aad299c3012877.output`
- **판정 본문 원본(위조 방지)**: `.harness/humansearch-inmail-machine-check.verdict.json` (repo 커밋) —
  findings 5건 + tried(반증 시도) 15항 전문 보존. repro 픽스처 `.harness/inmail_*_false_pass.txt` 등 커밋.
- codex 반증 시도(요지): 호칭 변형·성/이름 역순·빈 입력 fail-closed·NFC/NFD·비BMP 이모지·CRLF·
  1899/1900 경계·zero-width/전각 우회·R21 CTA 오탐·briefing warning — **깨려 했으나 실패**.
  기존 테스트 약화 없음(git diff 확인, 신규 파일).

### Claude 2차 (V2) — codex 판정 재공격, 격리 재현 (2026-07-03, 수정 커밋 95163dc)

| # | codex 발견 (severity) | 판정 | 조치 | V2 격리 재현 결과 |
|---|---|---|---|---|
| 1 | 'et'⊂'Meseret' 2글자 라틴 우연일치 fail-open (HIGH) | 사실 — 재현됨 | 포함일치 라틴≥3자/한글≥2자 제한 | repro exit 1, `name_mismatch` ✅ |
| 2 | '전 화' 공백 삽입 우회 (HIGH) | 사실 — 재현됨 | `전\s?화·통\s?화` 매칭(과잉차단은 fail-closed 허용) | repro exit 1, `call_request` ✅ |
| 3 | 언어 규칙 미강제 드리프트 (MED) | 사실 | **warning 승격**(STOP 아님 — 사장님 기계 STOP 5종에 언어 없음, 보고 후 진행) + 문서 명시 | repro ok=true + `language_mismatch` warning ✅ |
| 4 | P.S. CTA 미검사 (MED) | 사실 — Movensys ③ 절반 누락 | `ps_cta_missing` STOP 추가 | repro exit 1 ✅ |
| 5 | 단독 자모 vs goal `{2,}` 스펙 드리프트 (LOW) | 사실(문서 결함) | 코드(보수) 기준으로 goal·골든샘플 정정 + 회귀 고정 | `ㄱ 항목` STOP 테스트 ✅ |

- 양방향 의심(codex PASS 주장 독립 재현): 성/이름 역순 True·호칭 변형 True·빈 프로필 fail-closed·
  이모지 1자·CRLF 2자 — 전부 일치. 추가 공격: 한글 1자 토큰 우연일치 → len≥2 필터로 배제 확인.
- 상관 블라인드스팟(정직 표기): 이 게이트는 SKILL 문서가 CLI 실행을 강제하는 **문서 구동형** 배선이다
  (humansearch 자체가 문서 구동 스킬). LLM이 CLI를 건너뛰는 것 자체를 코드로 막을 수는 없고,
  doc-guard 테스트(AC8)가 SKILL의 강제 문구를 기계로 고정한다.
- 판정 정정 표: codex가 잡은 내 결함 5건 / 내가 codex에서 잡은 누락 0건(단 #3·#5는 STOP이 아니라
  warning·문서정정으로 등급 조정 — 근거 위 표).
- 수정 후 회귀 7건 추가, verify 767 passed + 3 xfailed, exit 0.
