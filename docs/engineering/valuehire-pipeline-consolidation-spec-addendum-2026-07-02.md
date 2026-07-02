# Valuehire 통합 파이프라인 Spec — 부록 2 (2026-07-02): 무인화 심화·매칭정밀도·개인화·완결감사

> 문서 경로: `docs/engineering/valuehire-pipeline-consolidation-spec-addendum-2026-07-02.md`
> 확장 대상(모(母) 문서): `valuehire-pipeline-consolidation-spec-2026-07-01.md`(44조각) + 백로그 JSON
> 근거: CLAUDE.md(SOT) · docs/harness.md(게이트) · 4영역 병렬 조사 + 적대검증(V1) 워크플로(2026-07-02, 9에이전트) · git/소스 재현
> 장부: `valuehire-pipeline-consolidation-spec-addendum-2026-07-02.verdict.json`

---

## (0) 한 줄 목적 — 사장님께

> 어제 만든 "한 줄기 파이프라인 설계도"는 **배관(부품)** 중심이었습니다. 이 부록은 사장님이 오늘 물으신 네 가지 — **①검색·매칭이 자동으로 돌 만큼 정교한가 ②개인화 편지가 최고 후보를 움직이는가 ③3사 JD가 잘 등록되는가 ④무인으로 돌리기엔 뭐가 막고 있나** — 를 실제 코드로 파고들어 확인하고, **어제 설계도에 빠져 있던 조각과 잘못 넣을 뻔한 조각**을 가려낸 결과입니다.
>
> 핵심 한 줄: **"부품은 거의 다 있는데, 정작 지금 이 작업방(브랜치)에는 어제 합친 안전장치(하드제외)가 빠져 있고, 무인으로 돌 상시 엔진은 잘못된 경로로 헛돌고 있습니다. 개인화 편지는 마지막 1cm가 비어 있습니다."**

이 부록의 모든 사실은 `파일:줄` 또는 git 재현으로 확인했고, 조사팀 주장 중 **검증에서 깨진 것은 제외**했습니다(§4 반박 로그).

---

## (1) 검증 통과 사실 요약 (영역별)

> `solid` = 검증팀이 반박 못 함. `needs_revision` = 일부 주장 반박됨(아래 §4 반영).

| 영역 | 검증 판정 | 확정된 핵심 사실(증거) |
|---|---|---|
| ① 매칭 정밀도 | needs_revision | 임베딩=sha1 어휘겹침 stub(`embed.py:38-49`), 키워드=substring 오탐(`humansearch.py:174`, **라이브 role_fit 0.50축**), seniority 컷 부재(`humansearch.py:123-139,209-226`), 러너 years_experience 미설정(`humansearch_cdp_run.py:151-161`) |
| ② 개인화 | needs_revision | 컴포저 코드 0(grep 0건), 템플릿 후보변수 0(`vendor md:229-265`), why_fit/CapturedProfile 산출되나 소비 컴포저 0, 출력계약엔 개인화 원재료(why_fit·profile_summary) 이미 존재 |
| ③ 3사 QA | **solid** | 브랜치-장부 불일치(PR#39/40/41 main-only, HEAD 22커밋 뒤), 러너면 하드제외 미호출(`humansearch_cdp_run.py`, main도 0건), 전수 하드캡 25(`:197`), SOT24 boolean/chip 결손, 러너 단일포지션·단일채널 하드코딩(`:39`) |
| ④ 무인 감사 | needs_revision | owner_activity_detected 생산자 0(항상 False), ExecuteHarvestItem 구현자 0, 페이싱 primitive 0, **데몬 크래시-루프**(Desktop 경로 부재+KeepAlive), BUG-BOOL-FAILOPEN·BUG-HARVEST-ASYNC 실재·미백로그, 런타임 OUT_DIR HOME 의존 |

---

## (2) 신규 조각 (7/1 백로그에 없음 — 검증 통과분만)

> 모두 "기존 계약 확장/주입, 신규 러너 금지"(SOT5) 원칙. ID는 7/1의 PC-* 뒤에 이어붙임.
> 각 조각은 별도 worktree에서 RED→GREEN→2패스(게이트 4b). 인수기준은 기계검증 가능한 1개.

### R11 — 채점·매칭 정밀도 (모 문서 R5·R6 심화)

| id | 제목 | 우선 | 의존 | 인수기준(요약) | 재사용/근거 |
|---|---|---|---|---|---|
| **PC-I1** | 졸업연도 파생 경력상한 컷(seniority_cap)을 hard_exclude에 코드화 | **P0** | PC-C0 | JD seniority_max=5에 졸업연도 파생 years=12 프로필이 `hard_exclude_reason(...)=='seniority_over_cap'`로 제외, ≤5년은 None(통과) | `humansearch.hard_exclude_reason` 확장 + `models.CapturedProfile.years_experience`. 근거: MEMORY 경력상한-졸업연도, `humansearch.py:123-139` |
| **PC-I2** | 러너가 졸업연도/근속에서 years_experience 산출(fail-closed) | **P0** | PC-C1a1 | 교육/dates 픽스처에서 졸업연도 있으면 정확산출, 없으면 근속합산 폴백, 둘 다 없으면 None | `humansearch_cdp_run.process_profile(:138-161)` + `scoring.count_short_tenure_hops`. 근거: 러너 years 미설정 |
| **PC-I3** | role_fit/education 매칭 substring→단어경계+별칭사전, 짧은토큰 화이트리스트, 'Berkeley College'류 오탐 봉인 | **P1** | PC-C0 | must 'account'가 'accounting only'에 미매칭(오탐0), 표기변형('자바'/'JAVA'/'Java')은 매칭, 'Berkeley College'는 명문대 판정 아님 | `humansearch._role_fit_subscore·_education_subscore` + `scoring._role_direct_score`를 공통 매처로 추출. 근거: `humansearch.py:172-178`, `humansearch_register.py:54` 오탐 자인 |
| PC-I4 | (미래 인프라) 운영 의미 임베더 주입 + CI sha1 stub 폴백 | P2 | PC-D3 | 페이크 semantic embedder로 match가 어휘 다르나 의미 같은 후보를 stub보다 상위 재랭킹, 미주입 시 stub 경로 바이트 동일 회귀 | `embed.py Embedder 주입점(:29,117)`. **주의: 현재 자율성 차단 아님** — embed/match는 프로덕션 호출자 0(고아). 라이브 배선(PC-D3) 후에만 의미. |

> **제외(반박됨):** "match.py에 하드제외 배선" — match.py는 고아이고 PC-D3 sot_guard가 하드제외를 등록/발송 단으로 확정. / "채점기 2중 병존 비결정" — 라이브는 `score_humansearch` 단일, `scoring.py` 경로는 고아라 현재 비결정 시나리오 없음(미래 배선 시 재검토).

### R12 — 개인화 아웃리치 (모 문서 R2·R10 심화; PC-G 확장)

| id | 제목 | 우선 | 의존 | 인수기준(요약) | 재사용/근거 |
|---|---|---|---|---|---|
| **PC-J1** | `build_outreach_context` 순수함수(PositionMatch+CapturedProfile → personalized_lines·emphasis_axis·segment 셀링축) | **P1** | PC-G2, (상류)PC-C1a | 주니어 3년 vs 시니어 10년 픽스처가 서로 다른 personalized_lines·emphasis_axis(성장 vs 임팩트) 반환, 부수효과 0. **하드제외 통과(eligible) 후보에만 적용** 전제 단언 | `models.PositionMatch·CapturedProfile` 재사용, 신규 모델은 OutreachContext 1개. 근거: 출력계약 why_fit/profile_summary 이미 존재 |
| **PC-J2** | 컴포저가 OutreachContext 소비(후보별 상이 산출) + R20 7요소·R21 CTA 유지 + PC-G1 캡 통과 | **P1** | PC-J1, PC-G2b | 동일 포지션·상이 두 후보 픽스처로 산출 문자열이 달라야(개인화 라인 포함) + `assert_outreach_jd_within_cap` 통과 동시 단언 | PC-G2 시그니처 확장 + PC-G1 캡가드(길이 로직 재구현 금지) |

> **제외(반박됨):** "신규 연봉 필드(compensation/last_salary_manwon)" — 이미 R9/PC-C5(`salary_raw` str, fail-closed)/PC-C6로 조각화됨. 정수 만원 파싱은 스펙이 §190에서 해소한 명명 드리프트를 되살림 → **PC-C5 재사용**. / "이름 개인화 배제" — direct composer의 `{{firstName}}` 리터럴 노출 방지 가드일 뿐, bulk 템플릿 모드는 토큰 동작(과장).
> **선행 전제(V1 지적 반영):** 개인화는 **상류 생산 배선**(PositionMatch·CapturedProfile을 라이브로 만드는 PC-C3a/PC-D5/PC-F2)이 먼저여야 end-to-end. 개인화는 파이프라인 **하류**다 — 위가 막히면 무의미.

### R13 — 무인 상시운영 안전·자립·장부무결 (모 문서 R3·R4·R5 심화)

| id | 제목 | 우선 | 의존 | 인수기준(요약) | 재사용/근거 |
|---|---|---|---|---|---|
| **PC-K1** | 브랜치/장부 무결 게이트 — red-ledger GREEN task-slug ↔ HEAD 실재 심볼 일치 CI 가드 | **P0** | 신규 | 각 GREEN slug의 대응 심볼(예: `eligible(results, channel)` + hard_exclude 호출)이 HEAD에 실재하면 통과, 부재면 비-0 종료 | red-ledger.tsv 파서 + .harness 게이트0 확장. 근거: PR#39/40/41 main-only, HEAD 22커밋 뒤 |
| **PC-K6** | 상주 데몬 크래시-루프 제거 + 경로 드리프트(Desktop→REPO_DIR) + dry_run→라이브 | **P0** | PC-D2b, PC-D2a2, PC-D5 | 데몬이 존재하는 REPO_DIR에서 실행되고, 부트 시 라이브 경로를 선택(페이크 실행자 호출횟수로 단언), 경로 부재로 KeepAlive 무한재시작 0 | `valuehire-search-loop.sh`/plist 교체. 근거: Desktop 경로 부재+`set -euo pipefail`+KeepAlive=크래시루프(V1 재현) |
| **PC-K2** | 라이브 러너 런타임 산출경로 자립화(OUT_DIR `~/.vh-search-results`→REPO_DIR 내부) | **P1** | PC-D2a2 | `humansearch_cdp_run.OUT_DIR`·`humansearch_register` 결과경로가 REPO_DIR 내부로 결정, `Path.home()/.vh-search-results` 참조 0건 | `humansearch_cdp_run.py:35`·`humansearch_register.py:94`. **PC-H1/H2(테스트 HOME)와 별개 런타임면** |
| **PC-K3** | BUG-BOOL-FAILOPEN 봉인 — boolean 채널 빈/공백 boolean_query fail-closed | **P1** | PC-B2b | 유효 keywords인데 boolean_query가 `''`/`'   '`이면 `KeywordGenerationError` raise(현행 조용통과=RED) | `llm_keywords.py:160/229` 강화. verdict PLAUSIBLE 승격 |
| **PC-K4** | BUG-HARVEST-ASYNC 가드 — 실행중 이벤트루프에서도 코루틴 실행자 안전 처리(fail-closed) | **P1** | PC-D5 | running loop 안에서 async execute_item 주입해도 RuntimeWarning/미await 없이 결과수집 또는 명시적 fail 로그 | `harvest_runner.py:76-79 _resolve`. **T 미재현 → 착수 시 재현 먼저(reproduce-first)** |
| **PC-K5** | 라이브 차단요인 감지 가드 — selectors-error-ledger 사례 STOP/알림 | **P1** | PC-F3 | tutorial URL / uiOrigin=GLOBAL_SEARCH_HEADER / 결과0건+필드 되읽기일치 각각에 '후보 없음'이 아닌 STOP+사유 반환 | `portal_login._has_security_challenge` 패턴 재사용. 근거: selectors-error-ledger 3행 프로즈만 |

> **제외/정정(반박됨):**
> - "owner-activity OS 센서 신설" → **제외**. `owner_activity.py`(`_macos_frontmost_app` osascript, `_macos_idle_seconds` ioreg HIDIdleTime, `detect_owner_activity_snapshot`)가 **`task/ai-search-pipeline-wip`에 이미 존재**하고 PC-F1 reuse_branch가 이걸 `compute_yield_decision`으로 살베지하도록 지정. 진짜 갭 = "미병합·미배선"이지 "부재" 아님.
> - "owner_activity_detected 라이브 배선 신규조각" → **제외**. PC-F2(러너 루프 양보/재개) + PC-D2b(드라이버 yield)가 이미 커버. **정정: PC-F1은 신규작성 금지, wip `owner_activity.py` 살베지.**

### 우선순위 상향 (모 문서 재분류)

- **PC-F4b(상주 데몬 라이브) P2 → P1**: 현재 데몬이 단순 미완이 아니라 **능동적으로 해롭다**(크래시-루프, SOT2 봇류 반복에 근접). PC-K6와 함께 처리.
- **PC-C3a(러너면 하드제외) 유지 P0**: main도 미배선. 하드제외 3면 중 러너면만 미완.

---

## (3) 완결 감사 — 무인화의 진짜 P0 척추 (사장님 #4 "남김없이 연결")

> 아래 순서가 "한 번 켜두면 도는" 무인화의 실제 차단 경로다. 위가 안 풀리면 아래(개인화)는 의미가 없다.

```
0. 장부무결 (PC-K1) + 현재 브랜치를 main으로 정합
   └ 지금 작업 브랜치엔 하드제외 P0(PR#39/40/41)가 아예 없음. 이걸 먼저 트리에 실재시켜야 나머지가 유효.
        │
        ▼
1. 라이브 실행 이음매 (PC-D5 ExecuteHarvestItem) + async 가드 (PC-K4)
   └ 구현자 0. 이게 없으면 상시 Harvest가 라이브로 단 한 번도 못 돎(dry_run만).
        │
        ▼
2. owner-activity 살베지+배선 (PC-F1 wip 살베지 → PC-F2/PC-D2b 라이브 주입)
   └ 센서 코드는 wip에 있음. 미병합·미배선이 문제. R4(양보·자동재개)의 심장.
        │
        ▼
3. 봇방지 페이싱 (PC-E1) — 위 라이브 루프들이 봇처럼 안 굴게(SOT2)
        │
        ▼
4. 러너면 하드제외 (PC-C3a) + 경력상한 (PC-I1/I2) + 매칭정밀도 (PC-I3)
   └ 라이브 산출물(results.json)에서 부적격자 차단 + 오탐 제거.
        │
        ▼
5. 데몬 크래시-루프 제거 + 자립화 (PC-K6 + PC-K2)
   └ 상시 엔진이 실제 경로에서 라이브로, 산출물은 레포 안에.
        │
        ▼
6. 개인화 아웃리치 (PC-J1/J2) — 하류. eligible 후보에만.
        │
        ▼
7. ★사람이 마지막 "보내기" (SOT3 — 불변)
```

**교차 빠진연결(영역 간):**
- 개인화(②)는 후보별 근거(why_fit)·프로필(CapturedProfile)을 소비하는데, 그 **생산 경로가 라이브 배선(1·2·4)이 되기 전엔 고아**다 → 개인화는 반드시 척추 이후.
- 매칭 정밀도(①)의 substring 오탐은 **라이브 채점(`score_humansearch`)에 그대로 적용**되므로 전수조사(PC-C3b)로 후보가 늘수록 악화 → PC-I3 우선순위를 전수조사와 함께 본다.
- 장부무결(PC-K1)이 없으면 위 모든 GREEN이 "이 트리엔 없는 코드"를 GREEN으로 자인할 수 있음 → **PC-K1이 0순위 메타 게이트**.

**미확정(구현 전 확정 필요):**
- 현재 브랜치 `chore/aisearch-tooling-sot`를 main에 rebase할지 cherry-pick(8bb4ea6/4e9f37a/7dd4e05)할지 — `humansearch_register.py` 동시편집 충돌 가능. 게이트0.5 회수 필요.
- BUG-HARVEST-ASYNC/BOOL-FAILOPEN은 T 미재현(PLAUSIBLE) — 착수 시 재현 먼저, 재현 안 되면 조각 취소.

---

## (4) 적대검증 반영 로그 (2026-07-02 · G=조사 → V1=검증 → T=git/소스 재현)

> 조사팀 4영역 산출(G)을 리셋 컨텍스트 검증자(V1)가 깼고, 아래는 그중 **반박이 성립해 스펙에서 제외/수정한 것**이다. 세션 워크플로 9에이전트, transcript = 이 부록의 verdict.json.

- **[④ high 반박] "owner-activity 센서 부재" 거짓** → `owner_activity.py`가 wip에 실재(osascript/ioreg), PC-F1 살베지 대상. 신규 "OS 센서" 조각 제외, PC-F1 살베지로 정정.
- **[④ med 반박] "owner_activity_detected 라이브 배선 신규"** → PC-F2/PC-D2b가 이미 커버. 제외.
- **[① high 반박] "채점기 2중 병존 비결정" / "match.py 하드제외 배선"** → match.py 프로덕션 호출자 0(고아), 하드제외 위치는 PC-D3에서 등록/발송 단으로 확정. 두 제안 제외.
- **[① med 반박] "의미 임베딩 부재가 현재 자율성 차단"** → embed/match 고아라 현재 미소비. PC-I4를 "미래 인프라 P2"로 강등.
- **[② high 반박] "신규 연봉 필드"** → PC-C5/C6 중복. 제외, salary_raw 재사용.
- **[② med 반박] "이름 개인화 배제"** → 기술적 리터럴 가드 오해. 과장 제거.
- **[③ 반박] "이 브랜치가 능동적으로 후보 유출(P0)"** → 라이브는 merged main 기준. 실제 문제는 **장부-코드 불일치(무결성)** → PC-K1로 프레이밍 정정(유출 프레임 철회).
- **[③ 반박] "must_haves 'ai' 오탐으로 지배축 부풀림"** → 'ai'는 nice_to_haves(0.2). substring 오탐 자체는 유효하나 인과 정정.
- **[④ V1 놓침 보강] 데몬은 dry_run이 아니라 크래시-루프**(경로 부재+KeepAlive) → PC-K6 우선순위 상향 근거.

**반영 안 함(후속):** 완결성 비평 에이전트가 "완결."만 반환(본문 부실) → 교차연결은 §3에서 내가 직접 합성. 상주 데몬·센서 실운영은 단일 pytest로 완결 판정 불가 → 순수 결정함수는 기계검증, 실운영은 수동 verdict(모 문서 §5 잔여리스크 계승).

---

## (5) ③ 3사 JD 등록 흐름 — 실제 QA (2026-07-02, 정적 + 준비완료)

> 사장님 #3("3사 JD 등록 절차가 원활한가 QA")의 결과. 사장님이 "실제 등록 1건 시험"을 택하셨으나, 등록은 **포털에 실제 기록이 생기는 바깥 작업**이고 확인 요청 시점에 사장님이 자리를 비우셔서(그리고 크롬 점유를 감지할 센서가 없음 — R4 갭) **자동 실등록은 보류**하고, 부작용 없는 정적 QA + 준비까지 완료했다. 복귀 후 "go" 한마디로 즉시 실행 가능.

**시험 대상(준비 완료):** `[포지션]이우소프트웨어(Vatech), Tech Proj. Manager` (ClickUp `86exuwb1c`, 상태 `po/pm/기획`, 실질 유일 활성 포지션). JD 본문 확보(회사=이우소프트/바텍네트웍스, 직무=Technical PM 7~12년, 근무지 동탄).

**준비 상태:** 크롬 디버그 9222 실행 중 ✓ · `.env.local` 포털 자격증명 4행 ✓ · 등록 셀렉터·함정 파악 ✓(사람인 `input[name=hiringTitle]`·[+포지션 추가], 잡코리아 `input[name=GI_PSTN]`·고용형태 dropdown CDP 마우스클릭·서치펌 세션 분리).

**정적 QA 결함(실측) — 등록 스킬의 파일 참조가 이 체크아웃과 어긋남(경로 드리프트, ④와 동근):**

| # | 스킬(전역 `~/.claude/skills/position-register`) 주장 | 이 저장소 실제 | 영향 |
|---|---|---|---|
| Q1 | `docs/sot/26-portal-login-spec.json` = "부재(죽은 참조)" (P1) | **실재**(14,832 B) | 스킬이 실재하는 로그인 SOT를 안 씀 → 로그인 절차가 스킬 인라인 서술에만 의존 |
| Q2 | `tools/jobkorea-bulk-register/auto-login.mjs` = "실재, 잡코리아 로그인 셀렉터 원본" (P1) | **부재** | 잡코리아 자동 로그인의 근거 파일이 없음 → 로그아웃 상태면 잡코리아 등록이 사람 게이트로 떨어질 위험 |
| Q3 | `tools/multi_position_sourcing/portal_autologin.py` = "부재, 가리키지 말 것" (P1) | **실재** | 스킬이 쓸 수 있는 자산을 배제 |
| Q4 | (P0 line14) raw CDP 연결법 근거로 SOT26 지목 ↔ (P1) SOT26 부재 선언 | 스킬 내부 자기모순 | 연결법 근거가 스킬 안에서 상충 |

> **판정:** 등록 **본문·셀렉터·함정**은 라이브 검증(2026-06-15/19)돼 견고. 그러나 **로그인 단계의 파일 참조가 이 저장소 기준으로 3개 틀렸다**(모두 Desktop 체크아웃 가정 → 경로 드리프트, 크래시-루프 데몬과 동일 뿌리). 사람인은 이미 로그인 세션이면 무해하나, **잡코리아 로그아웃 상태에서는 근거 파일(Q2) 부재로 자동 로그인이 불안정**할 수 있다.
>
> **신규 조각 PC-K7 [P1]:** position-register(및 자매 스킬)의 파일 참조를 이 저장소 실측 경로로 교정 — SOT26 실사용, jobkorea 로그인 셀렉터 출처를 실재 파일(auto-login.mjs 부재 → SOT26 channels.jobkorea 또는 실재 소스)로 재지정, portal_autologin.py 배제 문구 철회. depends: PC-K1(체크아웃 무결). 인수기준: 스킬이 인용하는 모든 경로가 `git ls-files`에 존재함을 검사하는 가드가 GREEN. **R6(스킬 작업)이므로 skill-creator 경유.**

**라이브 시험 결과(2026-07-02 완료 — 사람인 1건):** Vatech Technical PM을 사람인 인재풀(candidate-manage)에 **등록 성공**. 목록 맨 앞 카드 생성(생성자 강상모·2026.07.02), 진행중 428→429(+1)·등록가능 -1, 제안/발송 0(SOT3 준수·발송 안 누름). 절차: raw CDP 단일탭 attach → 로그인 확인(GNB "Valueconnect 강상모") → [포지션 추가] 패널 → React 인식 value setter로 포지션명(27)/제안내용(1,096)/업무내용(797) 주입·자모깨짐 0 → [저장]. §1.5 8요소 밀도(7/8, ④⑤ 그룹수치·⑦ quote 미확인 표기) 회사 브리핑 적용.
- **QA 판정:** 사람인 등록 흐름은 **라이브 정상**. Q1/Q3(SOT26·portal_autologin 참조 오류)는 사람인 세션이 이미 로그인 상태라 이번엔 미발동(무해). **Q2(잡코리아 auto-login.mjs 부재)는 잡코리아 로그아웃 상태에서만 터지므로 이번 사람인 시험으로는 미검증** → 잡코리아 라이브 시험은 로그아웃 상태에서 별도 확인 필요(PC-K7 대상).
- **미완:** 잡코리아 1건 등록 시험(로그아웃 상태 자동로그인 경로 Q2 실검증) — 사장님 지시 시 진행.

---

_생성: 2026-07-02 · 이 부록은 게이트1(스펙) 산출물이며 코드 변경이 아니다. 각 신규 조각은 별도 worktree에서 RED→GREEN→2패스(게이트4b, Codex V2 포함)로 이행한다._
