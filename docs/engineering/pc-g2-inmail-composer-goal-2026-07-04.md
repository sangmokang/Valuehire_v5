# PC-G2 구현 프롬프트 — LinkedIn InMail 개인화 문구 생성기 (`build_linkedin_inmail_jd`)

> 이 문서는 **게이트 1(스펙) 산출물**이자 **다음 작업 세션이 그대로 붙여 실행할 구현 프롬프트**다.
> 근거 SOT: `CLAUDE.md`(불변식) · `docs/harness.md`(게이트) · `docs/engineering/valuehire-pipeline-consolidation-spec-2026-07-01.md`(PC-G2 원 스펙) · 백로그 JSON PC-G2.
> 작업 방식: `/strict`(또는 `/st`) 모드로 시작. **한 워크트리 = 인수기준 1개.**

---

## 0) 한 줄 목적 (사장님께)

> 점수 매긴 후보 1명 정보를 넣으면 **개인화 제안 문구(InMail 본문)를 문자열로 자동으로 만들어내는 부품**을 만든다.
> 이 부품은 **글자만 만들어 돌려줄 뿐, 절대 보내지 않는다**(보내기는 늘 사장님 손). 방금 만든 글자수 안전장치(PC-G1)를 이 부품이 불러 쓴다.

---

## 1) 위험 등급 · 모드
- **모드: code-change. 위험등급: L2.**
  단일 순수함수 1개 + 테스트. 외부 발송·로그인·파괴 없음(문자열만 반환). 라이브 배선은 하류(PC-G2b/PC-D·humansearch #8)로 분리.
- L2 요구: RED→GREEN + 생성자(G) 자기 mutation + `verify.sh` exit 0 + **Codex(V1) 독립 적대검증 1패스**(CLAUDE.md 5번). 3자(V2)는 하드제외/발송 경계를 직접 건드릴 때만 승격.

---

## 2) 계약 먼저 (SDD — 입출력을 코드 짜기 전에 박는다)

### 2.1 함수 시그니처 (신규 모듈 `tools/multi_position_sourcing/jd_outreach.py`에 추가 — PC-G1과 같은 파일)
```python
def build_linkedin_inmail_jd(
    *,
    candidate_name: str,            # 수확 JSON 의 name 그대로. 인사말에 그대로 박음(손 재입력 금지)
    personalized_opener: str,       # ① 정곡 관찰 1줄(이력 요약·나열 금지). 호출자가 제공
    company_name: str,
    position_title: str,
    company_briefing: dict,         # BRIEFING_ELEMENT_KEYS(8키) → 값(출처 있는 사실). 미확인은 생략 또는 "※미확인"
    jd_responsibilities: list[str], # [주요 업무] 불릿 원천(윤문된 문장들)
    jd_qualifications: list[str],   # [자격 요건] 불릿 원천
    why_consider: list[str],        # [왜 검토할 만한가] 2~3불릿
    location: str | None = None,
    language: str = "ko",           # "ko"|"en". body_language_for_profile() 로 호출자가 결정
    channel: str = "linkedin_rps",
) -> str:
    """골든샘플 v2 구조로 InMail 본문 문자열을 조립해 반환. 부수효과 0(Send/insert 없음)."""
```

### 2.2 출력 계약 (반환 문자열이 반드시 만족)
반환된 `body` 는 **이미 배송된 검사기를 그대로 통과**해야 한다(생성기·테스트가 서로 베끼는 가짜 GREEN 방지 — 검사기가 독립 oracle):
1. `precheck_inmail(body, profile_name=candidate_name, channel=channel, briefing_elements=<채운 요소 dict>)` → `ok=True`
   - 이게 한 방에 커버: ① 인사말 이름=candidate_name ② 채널 글자수 한도 ③ 금지워딩 0(통화·과장·중괄호·HTML주석) ⑤ 자모분리·오타 0 ⑥ VERIFIED-PULL 문단 + P.S. CTA 존재. 브리핑 6요소 미만은 STOP 아님(보고).
2. `assert_outreach_jd_within_cap(body, channel=channel)` 예외 없이 통과(PC-G1 재사용 — 길이 로직 재구현 금지). ※ 실제 캡 강제 단언은 PC-G2b 몫.
3. **부수효과 0** — 문자열만 반환. 파일 쓰기·네트워크·브라우저 호출 없음(SOT3).

### 2.3 조립 구조 (골든샘플 v2 = `skills/humansearch/references/inmail-golden-sample.md` 그대로)
```
[제목] {company_name}, {position_title}
안녕하세요 {candidate_name}님,
저는 테크 서치펌 밸류커넥트(Valueconnect)의 헤드헌터 강상모라고 합니다.
{personalized_opener}                    ← ① 이력 요약 금지, 정곡 관찰 1줄
[회사] {company_briefing 8요소를 불릿으로, 출처 있는 것만}   ← R20
[주요 업무] {jd_responsibilities 불릿}    ← R20 JD
[자격 요건] {jd_qualifications 불릿}
[왜 검토할 만한가] {why_consider 2~3불릿}  ← "딱 맞다"류 과장 금지
{VERIFIED-PULL 고정 문단 — language 에 맞춰 한/영}          ← ⑤ 필수
{클로징 + "강상모 드림"}
P.S. {R21 고정 CTA — https://valuehire.cc/resume}          ← ⑥ 필수
[근무지] {location}   (있으면)
```
- VERIFIED-PULL 문단·P.S. CTA 는 **함수가 고정 삽입**(호출자 입력 아님) — 누락 자체를 구조적으로 불가능하게.
- 꺾쇠 `<>`·중괄호 `{}`·raw `{{}}`·HTML 주석 **출력에 절대 남기지 않는다**(R25).

---

## 3) 재사용(SOT5) — 새로 만들지 말 것, 이미 있는 걸 부른다
| 필요 | 재사용 대상 | 경로 |
|---|---|---|
| 글자수(NFC) | `char_count` | `tools/multi_position_sourcing/inmail_precheck.py:89` |
| 채널 한도 1899/2000 | `CHANNEL_CHAR_LIMITS` | `inmail_precheck.py:48` |
| 캡 가드 | `assert_outreach_jd_within_cap`·`OutreachJdCapError` | `jd_outreach.py`(PC-G1, 이미 병합) |
| 회사 브리핑 8키·최소6 | `BRIEFING_ELEMENT_KEYS`·`BRIEFING_MIN_ELEMENTS`·`count_briefing_elements` | `inmail_precheck.py:34,44,161` |
| 발송 전 전체 검사 | `precheck_inmail` | `inmail_precheck.py:247` |
| 언어 판정 | `body_language_for_profile` | `inmail_precheck.py:198` |
| 문구 구조·절대규칙 | 골든샘플 v2(복제 말고 읽어서 따름) | `skills/humansearch/references/inmail-golden-sample.md` |

⛔ 신규 러너/스크립트/제2 길이함수/제2 브리핑상수 금지. 3채널(사람인·잡코리아) 컴포저 신설도 이 조각 범위 아님(PC-G3).

---

## 4) ⚠️ 착수 전 확정할 계약 모호점 (게이트 1에서 결정 — 감으로 코딩 금지)
1. **브리핑 요소 개수 7 vs 8.** 백로그 AC는 "R20 **7요소**"라는데 현행 SOT(`inmail_precheck` 8키 + `BRIEFING_MIN_ELEMENTS=6`, 전역 스킬 2026-07-02 "8요소로 상향")와 어긋난다.
   → **해소: `BRIEFING_ELEMENT_KEYS`(8키)를 단일 진실로 삼고, 테스트는 `count_briefing_elements(...) >= BRIEFING_MIN_ELEMENTS`(6)로 단언**한다. "7요소 전부"라는 옛 문구에 하드코딩하지 말 것(SOT5 재사용). 이 결정을 goal 문서 `적대검증 로그`에 근거와 함께 남긴다.
2. **subject 반환 형태.** 본문만 반환할지, `(subject, body)`를 반환할지. → 기본: **본문 문자열만 반환**(AC가 "반환 문자열"이라 단수). subject 는 본문 첫 줄 `[제목]`으로 포함. 별도 필요 시 후속 조각.
3. **입력 검증 강도.** `company_briefing` 에 금지워딩/중괄호가 섞여 들어오면? → 함수는 **조립만** 하고 최종 판정은 `precheck_inmail` 에 위임(단일 검문소). 단 함수가 **스스로 금지워딩을 추가하지 않음**을 테스트로 못박는다.

---

## 5) 인수 기준 (기계 검사 — `tests/test_linkedin_inmail_jd.py`)
백로그 PC-G2 AC를 이 조각의 단언으로:
- **AC-1 (골든 통과):** ax-sales-lead 골든 픽스처(§ 아래 픽스처)를 입력하면 반환 `body` 에 대해
  `precheck_inmail(body, profile_name=candidate_name, channel="linkedin_rps", briefing_elements=briefing)` 의 `ok is True` (금지워딩 0·이름일치·VERIFIED-PULL·P.S. CTA 동시 만족).
- **AC-2 (브리핑 요소):** `count_briefing_elements(briefing) >= BRIEFING_MIN_ELEMENTS` 이고, 반환 body 에 각 채운 요소의 값 문자열이 실제로 포함됨.
- **AC-3 (P.S. CTA):** `"valuehire.cc/resume"` 와 P.S. 문단이 body 에 존재(부재 시 실패). VERIFIED-PULL 문단도 존재.
- **AC-4 (부수효과 0):** 함수 호출이 문자열만 반환(모듈에 네트워크/파일/브라우저 import·호출 없음). `monkeypatch` 로 파일/네트워크가 불리면 실패하도록 감시하거나, 반환 타입·순수성 단언.
- **AC-5 (이름 일치·손재입력 금지):** 인사말의 이름이 입력 `candidate_name` 과 정확히 일치(부분·오타 시 `precheck_inmail` ① STOP).
- **AC-6 (금지워딩 비주입):** `personalized_opener`·`why_consider` 가 깨끗한 입력일 때 함수가 "통화/전화"·"딱 맞다"·중괄호를 **스스로 추가하지 않음**(정상 입력 → precheck 통과).
- `verify.sh` **exit 0**(출력 숫자 그대로 보고).

### 픽스처(골든) — `docs/todo/ax-sales-lead-rps-jd-template.md` 원문에서 구조화
```
candidate_name = "<테스트용 로마자 한국 이름, 예: Jihoon Park>"
personalized_opener = "B2B/B2G 영업 커리어가 인상 깊어, 한 분만 보고 연락드립니다."
company_name = "뤼튼테크놀로지스"; position_title = "AX Sales Team Lead"
company_briefing = {
  "one_line":"2021년 설립된 국내 대표 생성형 AI 기업",
  "ceo_quote":"대표 이세영 — \"AI는 공기처럼 모두가 누리는 존재여야 한다\"",
  "funding_stage":"시리즈B 1,080억원, 누적 1,300억원+",
  "revenue":"2025년 연매출 300억원 상회", "headcount":"약 90명",
  "history":"2021 설립·생활형 AI 전환", "recent_news":"기업용 AI 전환(AX) 사업 확대",
}  # 7키 채움 → count>=6 통과
jd_responsibilities = ["기업·정부 대형 딜 직접 발굴·클로징", "세일즈 플레이북 수립·팀 이식", "신규 세그먼트·GTM 전략", "0→1 세일즈 조직 구축"]
jd_qualifications = ["B2B/G 대형 딜 직접 성사 실적", "협상·계약 체결·팀 성장 경험", "AI 도메인 미경험 무방"]
why_consider = ["플레잉 리드 권한", "0→1 조직 구축", "대형 딜 최전선"]
language = "ko"
```
> ⚠️ 픽스처는 **테스트 파일 안에만** 둔다. 라이브 실이름·실회사 하드코딩 금지. `candidate_name` 은 로마자 한국 이름으로.

---

## 6) 게이트 (harness — 순서 고정, 건너뛰기 금지)
0. **시작자격.** `make red-ledger` GREEN(현재 `anti-bot-pacing` RED 병행 항목이 있으면 그 세션과 충돌 없는지 확인 — 파일 스코프 `jd_outreach.py`/신규 테스트만 건드림). 깨끗한 컨텍스트.
0.5 **과거 회수.** 이 문서 §3 재사용표 + `reuse_branch=task/track-claude-skills`(스킬 벤더링) 상태 확인. `build_linkedin_inmail_jd` 심볼이 아직 없음을 `grep` 으로 재확인(중복 구현 금지).
1. **스펙.** 인수기준 §5(위 6개 + verify exit 0). GitHub 이슈 1개.
2. **RED(워크트리).** `make task NAME=linkedin-jd-composer` → `worktrees/linkedin-jd-composer` + `task/linkedin-jd-composer`. §5 단언을 실패 테스트로 먼저 커밋(모듈에 함수 없음 → import/AttributeError RED).
3. **구현.** `jd_outreach.py` 에 `build_linkedin_inmail_jd` 추가(파일 1개, diff 목표 ≤150줄). 고정 문단(VERIFIED-PULL·P.S.) 상수화.
4. **검증.** `./verify.sh` exit 0 + 숫자 그대로. 생성자 mutation 최소 1개(예: P.S. 문단 조립 제거 → AC-3 실패해야, VERIFIED-PULL 제거 → AC-1 실패해야) 넣었다 되돌려 테스트 물림 증명.
5. **배송.** `make ship` → PR. CI 초록 + merge 전 완료 없음. `.harness/*.verdict.json` 에 G+V1 기록.
6. **종료.** merge 후 `git worktree remove` + 장부 GREEN 마감 + `/clear`.

---

## 7) 적대검증 정조준 (V1=Codex 에게 깨보라 할 지점)
- **고아 여부(R4):** `build_linkedin_inmail_jd` 가 아무도 안 부르면 고아. 이 조각은 **seam**(계약)으로 허용 — 단 goal 문서에 "소비자 = humansearch #8 문구 작성 + 하류 PC-D 발송 드래프트"라고 명시하고, 후속 배선 조각(#8이 이 함수를 부르게)을 백로그에 남긴다. "만들었지만 아무 데도 안 씀"으로 방치 금지.
- **가짜 GREEN:** 테스트가 `precheck_inmail`(독립 검사기)을 oracle 로 쓰는지(구현 문자열을 그대로 비교하는 tautology 아닌지).
- **부수효과 누출:** 함수 안에서 파일/네트워크/브라우저를 실제로 부르지 않는지(SOT3).
- **금지워딩 자체 주입:** 고정 문단·조립 과정에서 "통화"·"딱 맞다"·중괄호가 새로 들어가지 않는지.
- **글자수 경계:** 긴 브리핑/JD 입력 시 1,899 초과를 조용히 통과시키지 않는지(→ 이건 PC-G2b가 STOP 강제. G2에서는 최소한 `assert_outreach_jd_within_cap` 를 호출은 하되 STOP 강제 단언은 G2b).
- **이름 손재입력:** 인사말 이름이 `candidate_name` 과 1바이트라도 다르면 STOP(Movensys 사고 재발 방지).

---

## 8) 비범위 (이 조각에서 하지 않음)
- 실제 브라우저 컴포저 입력·`Save as new template`·Send (humansearch #8 / jd-set-builder 스킬 관할, 늘 사람 발송).
- 사람인·잡코리아·Gmail 채널 컴포저(→ PC-G3).
- 1,899 캡 초과 STOP 강제 단언(→ PC-G2b).
- 개인화 오프너·브리핑 사실 자체의 수집(호출자·humansearch가 제공; 이 함수는 조립만).

## 적대 검증 로그 (2026-07-04 구현 세션)

- **브리핑 7 vs 8 결정**: `BRIEFING_ELEMENT_KEYS`(8키) + `BRIEFING_MIN_ELEMENTS`(6)를 단일 진실로 채택.
  근거: 현행 SOT(`inmail_precheck.py:34-44`, 골든샘플 v2, 전역 스킬 2026-07-02 "8요소 상향")이 백로그의 옛
  "R20 7요소" 문구보다 우선(SOT5). 테스트는 `count_briefing_elements(...) >= 6` 단언, 7요소 하드코딩 없음.
- **정합성 수정**: 본 문서 §2.2 의 `precheck_inmail(..., briefing_elements=<dict>)`는 실제 시그니처와 다름 —
  실제 인자는 `briefing_element_count: int` (기존 `count_briefing_elements()`로 개수를 세서 전달, 재구현 없음).
- **RED 증거**: 커밋 96ef48e (ImportError — 함수 미구현 상태에서 인수기준 테스트 먼저 커밋).
- **mutation 증거(G)**: ①P.S. CTA 제거→3 failed ②VERIFIED-PULL 제거→3 failed ③이름 하드코딩→2 failed
  ④캡가드 호출 제거→최초 생존→spy 배선 테스트(ed4aed4)로 봉인 후 1 failed. 전 mutant 사멸.
- **V1(codex-rescue, 독립 세션) 8라운드**: 상세는 `linkedin-jd-composer.verdict.json`.
  blocking 발견→봉인 이력: zero-width ※미확인 우회(7aa14c8) → 마커 변형·비문자열(9c1b454) →
  전 경로 공통검문(5147b55) → None 항목·language/channel 타입(783a709) → 제어문자 주입(3cd6e2e) →
  U+2028/29 자기반증(5352615) → 예약 헤더 위장(d0ad0a1) → 유니코드 공백 접기(3c24d02).
  **round8 최종 pass** (남은 findings 는 전부 followup — 한자 혼용·렌티큘러 괄호·HTML 태그 등 고의적 조작 수준,
  내부 호출자 위협모델상 수용. 발송 직전 사람 확인 + 스크린샷 대조 절차가 최종 안전망).
- **범위 밖 분리**: precheck 이름검사 부분일치 오탐(순서 뒤집힌/잘린 이름 통과) → 이슈 #60.
- **T(기계)**: `./verify.sh` — `906 passed, 3 xfailed, 5 subtests passed` exit 0.
