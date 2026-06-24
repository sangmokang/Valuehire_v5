# goal 프롬프트 — AI Search 검색 로직: 채널별 촘촘 구성 + 다단 완화 재시도 (PR#31 후속·재정의)

> 이 문서는 **다음 작업방에서 그대로 읽고 시작**하는 goal 프롬프트다.
> 최초 작성 2026-06-24(PR#31 머지 직후) → 같은 날 **사장님 지시로 범위 재정의**(LinkedIn 한 채널 → 3채널 + 다단 재시도).
> 근거 `file:line` 은 직접 확인한 값 — **다음 세션은 시작 시 grep/Read 로 재확인**하고 드리프트 시 갱신할 것.
> ⚠️ `/st`(엄격) 모드로 진행. 코드 변경 = L3. 전용 worktree 필수.

---

## 0. 한 줄 배경 — 무엇이 바뀌었나 (사장님 2026-06-24 지시)

처음 이 방의 숙제는 "LinkedIn 한 채널에 boolean 검색식을 흐르게"였다. 사장님이 범위를 넓혔다:

> **"AI Search 할 때 검색 로직을 더 촘촘하게 구성하고, 몇 차례에 걸친 시도를 해서 좋은 후보자를 얻는 것"이 목표가 되어야 한다.**
> 그리고 채널마다 검색칸 구조가 다르니 **각 채널의 칸 구조에 맞게** 같은 검색 의도를 다르게 표현해야 한다.

즉 이 작업의 중심은 더 이상 "boolean 한 문자열"이 아니라 **(1) 채널별로 알맞은 검색식 구성 + (2) 한 번에 끝내지 않고 정밀→표준→확장으로 여러 번 시도하는 완화 루프**다.

## 1. 채널별 검색칸 현실 (사장님 확인 = SOT 입력, 2026-06-24)

코드(`models.py:9-12`)는 원래 "사람인/잡코리아는 AND/OR 지원이 **라이브 미검증**이라 평문만"이라고 적어 두 채널을 boolean에서 뺐다. 사장님이 그 미검증 부분을 **확정**해 주셨다:

| 채널 | 검색칸 구조 | 검색 로직을 어떻게 넣나 |
|---|---|---|
| **사람인** | `AND` / `OR` / `NOT` 가 **각각 별도 필터칸** | 한 문자열 boolean이 아니라, 의도를 **필드별로 분배**한다. 예: 필수스킬→AND칸, 동의어/유사직무→OR칸, 제외어→NOT칸. |
| **잡코리아** | **칩(chip) 누적식** — 키워드 하나 입력 → 칩 1개 생성 | 괄호 boolean을 한 칸에 못 넣는다. **엄선된 단일 키워드를 하나씩 추가해 칩을 쌓아** 필터를 만든다. 칩들은 **기본 OR 결합**. → "정확한 키워드 N개"를 골라 순차 투입하는 게 핵심. |
| **링크드인 RPS / public_web** | `searchKeyword` 한 칸에 **X-ray boolean 문자열** | `("Title" OR …) AND ("Skill" OR …)` 풀 boolean 그대로. (PR#31에서 배관 일부 완성) |

> ⛒ **핵심 설계 결론:** "boolean_query 한 문자열"이라는 단일 표현으로는 3채널을 못 덮는다.
> **검색 의도(직무·핵심스킬 2~3·도메인)는 한 번 만들고, 채널별 렌더러가 그 의도를 각 칸 구조로 변환**해야 한다.
> → 그래서 `models.py`의 `BOOLEAN_CHANNELS`(linkedin/public_web만)라는 이분법은 **채널별 검색 표현 어댑터**로 일반화돼야 한다.

## 2. 현재 코드 상태 (file:line — 재확인 필수)

- `tools/multi_position_sourcing/models.py:7` — `Channel = Literal["saramin","jobkorea","linkedin_rps","public_web"]`.
- `tools/multi_position_sourcing/models.py:9-12` — `BOOLEAN_CHANNELS = {linkedin_rps, public_web}`. 사람인/잡코리아 제외 근거 = "AND/OR 라이브 미검증". **이 전제가 §1로 갱신됨.**
- `tools/multi_position_sourcing/llm_keywords.py:145` — `base_filters = {"boolean_query": plan.boolean_query}`. boolean_query 를 채우는 유일한 곳(`build_llm_keyword_sessions` / `build_llm_queue_items`).
- 위 두 함수는 **프로덕션 어디서도 호출되지 않음**(grep 재확인 필요 — PR#31 시점 정의부·tests 외 0건). ← 여전히 핵심 구멍.
- `tools/multi_position_sourcing/grouping.py:108` → `build_keyword_plan`(`keywords.py:94`) → `KeywordSession.filters = group.filters_by_channel[channel]` = **native 필터만, 검색식 키 없음.** 라이브가 실제로 쓰는 경로.
- `tools/multi_position_sourcing/dry_run.py:115` — QueueItem 을 `group.keyword_plan`(grouping 산출)에서 만든다.
- 소비측(PR#31 GREEN): `portal_queue_executor._query_for_session` 가 boolean 채널이면 `filters['boolean_query']` 를 검색어로 채택 → `portal_worker.py:368` `searchKeyword={quote(keyword)}`.
- 규칙 문서: `skills/search/references/boolean-strategy.md` — STEP A~B·D 구현, **STEP C(3단)·E(완화 루프) 미구현**.

## 3. 근본 원인 / 핵심 질문

1. **표현 구멍**: 지금 시스템은 검색 의도를 "boolean_query 한 문자열"로만 표현 → 사람인(필드 분배)·잡코리아(단일칸 압축)를 못 담는다.
2. **배관 구멍(PR#31 잔여)**: LLM 키워드 생성 경로와 라이브 실행 경로(grouping→dry_run→executor)가 **분리**돼, 생성기를 라이브에 안 이으면 영원히 잠든다.
3. **재시도 구멍**: 지금은 한 번 검색하고 끝. "통과 후보가 적으면 검색식을 완화해 다시"라는 **다단 루프가 없다.**

## 4. 목표 = 촘촘한 검색 + 다단 완화 재시도 (이 방의 중심)

한 번에 완벽한 검색식을 노리지 않는다. **좁게 시작 → 부족하면 넓힌다:**

```
정밀(precise)  : 직무 + 핵심스킬 2~3 + 도메인  (가장 좁게, 정확도 우선)
   │  통과 후보 < 목표수(예: 5명) 이면 ↓
표준(standard) : 동의어/유사직무까지 OR 확장
   │  여전히 부족하면 ↓
확장(expanded) : 도메인/부가조건 완화 (단, native 하드필터는 안 풂)
   └ 3단에서 종료(무한 반복 금지 — 봇처럼 같은 검색 반복은 R4 위반)
```

각 단계의 **검색 의도**는 채널 무관하게 한 번 생성하고, **채널 렌더러**가 §1 표대로 변환한다:
- 사람인 → AND/OR/NOT 필드 배분
- 잡코리아 → 칩 누적용 **단일 키워드 리스트**(엄선된 N개를 하나씩 추가, OR 결합)
- 링크드인/public_web → X-ray boolean 문자열

### ⛒ 결과 수에 따른 처리량(전수 여부)는 **이미 스킬에 있음 — 재발명 금지(SOT 5번)**
사장님이 2026-05-22에 이미 지시한 정책이 `saramin-talent-sourcing`(1456·1471~1490줄)·`jobkorea-talent-sourcing`(1585·1601~1620줄)에 명문화돼 있다. 완화 루프(슬라이스 C)는 **이 표를 그대로 따른다**:

| 검색 결과 수 | 처리 |
|---|---|
| 5~80명 | **GOLD = 전수** (모두 열어 저장·적합도 평가) |
| 81~300명 | **상위 40명(2페이지)만** 처리 후 다음 시나리오 |
| >300명 | 전수 안 함 → 검색식 **더 좁혀** 재시도 |
| 0~소수 | 검색식 **완화**해 빠르게 다른 시나리오 |

> 적합도 판정 자체(프로필 하나씩 열어 3축 85점)는 **현재 수동 스킬이 브라우저로 수행**한다. 자동 큐(`portal_queue_executor`)는 **결과 카드 개수만 집계**하고 프로필 열기·채점은 미배선(`models.py:166-172`, `portal_queue_executor.py:11-12`). → "자동 전수 열람·채점"은 별도 후속 배선이 필요하다(이 문서 범위 밖, 슬라이스 C 이후).

### ⛒ 학력 컷 — 전수 안 함, 클릭 대상을 먼저 좁힌다 (사장님 2026-06-24, memory `education-tier-screening`)
- **전수 조사 안 함.** 결과 리스트에서 학력 컷 미달 후보는 **프로필 상세 진입(클릭) 자체를 생략**한다.
- **클릭/통과 기준 — 다음 이상만:** 인서울 대학교 · 지방 국공립대 · 순위가 단국대 정도 이상. 그 미만(하위권)은 클릭 안 함.
- 적용 위치: **프로필-오픈(스크리닝) 단계** — 슬라이스 A(검색식 주입)가 아니라 그 다음 열람 단계. 현재는 수동 스킬의 "좋은학교" 축 정의로 사용, 자동 배선 시 결과 카드/프로필 학교명 파싱 후 컷.

## 5. 작게 자르기 — 슬라이스 재구성 (각각 별도 worktree·별도 PR)

### 슬라이스 A (먼저) — 검색 의도 → 라이브 keyword_plan 주입 + 채널 렌더러
- **목표**: 라이브 grouping/queue 경로가 각 채널 세션에 **그 채널 칸 구조에 맞는 검색식**을 실제로 담는다.
- **인수 기준(EARS)**:
  - `If 라이브 검색이 링크드인/public_web 포지션을 처리하면, then KeywordSession.filters 에 비어있지 않은 X-ray boolean 문자열이 실린다.`
  - `If 라이브 검색이 사람인 포지션을 처리하면, then 검색 의도가 AND/OR/NOT 필드별 값으로 분배돼 실린다.`
  - `If 라이브 검색이 잡코리아 포지션을 처리하면, then 칩 누적용 엄선 키워드 리스트(OR)가 실린다.`
- **검증**: pytest — 가짜 결정론 LLM으로 돌 때 채널별로 올바른 표현이 세션에 실리는지.
- **라이브 1건 실증(L3 필수)**: 실제 포지션 1건으로 생성→executor→각 채널 검색 URL/필드 조립까지 추적(브라우저 **발송 아님**, 조립까지만 — R3 발송금지 준수).
- **counter-AC(가짜완료)**: ①잡코리아 단일칸에 괄호 boolean 통째로 밀어넣어 0건 깨진 검색 ②사람인 필드 분배 없이 한 문자열만 ③LLM 실패를 조용히 삼켜 빈 검색식으로 통과(`KeywordGenerationError` 가 살아있어야).

### 슬라이스 B — 채널별 렌더러 + 3단(정밀/표준/확장) 생성
- `boolean-strategy.md` STEP C 구현. LLM 한 번 호출로 **검색 의도 1개**를 내고, 그걸 3단 × 3채널 표현으로 전개.
- **AC**: `Where 검색 계획이 생성되면, 시스템은 precise/standard/expanded 3단을 내고, 각 단은 직무+핵심스킬(2~3)+도메인만으로 구성(연차·지역·OTW 제외)하며, 채널별 칸 구조(사람인 필드분배 / 잡코리아 칩리스트 / 링크드인 boolean)로 렌더된다.`
- **counter-AC**: 3단이 사실상 동일 문자열(완화 효과 없음) / 연차·지역이 검색식에 새어듦 / 한 채널 표현을 다른 채널에 그대로 복사.

## 5.5 검색필터 출력 계약 (SDD — 슬라이스 B 코드 반영의 기준점·테스트 잣대)

AI Search 2단계가 채널별 세션 `filters` 에 싣는 구조. 검색 의도(직무 + 변별 핵심기술 2~3 + 도메인) 1개에서 채널 렌더러가 전개한다. 셀렉터(소비측)는 **이미 스킬에 있으니 재발명 금지**.

```python
# 사람인(saramin) — AND/OR/NOT 칸 분배 (소비측 셀렉터: skill 208~210)
filters["saramin_search"] = {
    "and": ["변별 핵심기술1"],                 # 반드시 보유 → div.search_word_include
    "or":  ["직무명", "직무 동의어", "유사직무"],  # 하나라도 → div.search_default
    "not": ["신입", "인턴", "프리랜서"],         # 제외 → div.search_word_except (기본값)
}

# 잡코리아(jobkorea) — 칩 누적(OR), 키워드 입력 후 Enter 등록 (소비측: skill 353~369)
filters["jobkorea_chips"] = ["엄선 키워드1", "엄선 키워드2", ...]   # 기본 OR. AND칩 추가는 슬라이스 C(완화)

# 링크드인/공개웹 — 기존(슬라이스 A 완료)
filters["boolean_query"] = '("A" OR "B") AND ("C" OR "D")'
```

**계약 불변식(테스트가 강제):**
1. `and/or/not`·`chips` 에 **연차·지역·연봉·OTW 안 넣음**(0건 방지) — 직무+핵심기술+도메인만.
2. `not` 기본값 = `["신입","인턴","프리랜서"]`(skill SOT). 비면 안 됨.
3. **채널 격리:** 평문 채널 filters 에 `boolean_query` 안 섞임, boolean 채널에 `saramin_search`/`jobkorea_chips` 안 섞임.
4. 빈 생성(키워드 0개)은 `KeywordGenerationError` — 조용히 빈 채로 통과 금지(슬라이스 A와 동일 원칙).
5. **정직 경계:** 본 슬라이스는 위 구조를 **생성해 큐에 싣는 층**까지. 실제 사람인 칸 입력·잡코리아 칩 Enter 의 **라이브 브라우저 실행은 보류**(봇탐지) — 슬라이스 A와 동일.

### 슬라이스 C — 완화 루프(다단 재검색) + 다건 그루핑 순차 서치 (가장 무거움·마지막)
- `boolean-strategy.md` STEP E. **통과 후보 < 목표수 → 정밀→표준→확장 순으로 재검색.** queue/executor 의 재실행 제어 흐름 변경 = 가장 위험 → 단독 worktree·단독 PR.
- 다건 발견 시 기술 유사도/연차대/도메인 그루핑 후 그룹별 순차 서치.
- **AC**: `If 한 단계 검색의 통과 후보가 목표수 미만이면, then 다음 단계 검색식으로 재검색해야 하고, 3단에서 반드시 종료한다(무한 반복 없음).`
- **counter-AC**: 완화가 native 하드필터까지 풀어 무관 후보 유입 / 같은 검색 무한반복(R4 위반) / 종료조건 없음.

## 6. SOT·불변식 체크 (시작 전 읽기)
- 루트 `CLAUDE.md` — 쉬운 한국어 보고, **발송 자동금지**(제안·메일은 사람이 마지막에), 크롬 양보·자동재개(R4), 코드 두 번 깐다.
- memory `ai-search-no-v4-code` — **v4 코드 절대 비의존**, v5(`tools/multi_position_sourcing/`)만.
- `docs/harness.md` 게이트 + `make red-ledger / task / verify / ship`.
- 검증 인터프리터: 워크트리에 venv 없음 → `ln -sfn /Users/kangsangmo/Valuehire_v5/.venv-playwright .venv-playwright` 후 `./verify.sh`(또는 `make verify`). push 는 SSH 막힘 → `git push https://github.com/sangmokang/Valuehire_v5.git <branch>`.

## 7. 비범위 (이 후속들에서도 안 함)
- 제안·InMail **발송**(항상 사람 게이트). 캡차·2FA 자동우회 금지.
- 완화 루프가 native 하드필터(연차·지역 등)를 푸는 것 — 검색식(키워드)만 완화, 하드필터는 유지.

## 8. 적대검증 — **생성자(나)의 자백**: 내가 약하다고 의심하는 곳

> ⚠️ **이 목록은 검증자에게 주는 "정답표"가 아니다.** (사장님 2026-06-24 지적: 만든 사람이 검증 포인트를 미리 적어 "여기만 보면 됨"이 되면 독립 검증이 아니다.)
> 검증자(V1 Codex fresh / V2 리셋 Claude)에게는 **이 골 문서 + 주장만** 주고 "통과"라는 결론은 빼서 **스스로 독립적으로 깨게** 한다. 아래는 내가 *먼저 자백*하는 약점일 뿐 — 검증자는 **여기 없는 곳도 반드시 공격**해야 한다.

- (자백 1) 슬라이스 A의 "라이브 연결"이 진짜 프로덕션 엔트리포인트에서 호출되는가, 아니면 또 dormant 함수에 붙였는가(PR#31의 교훈). → 엔트리→호출그래프 끝까지 런타임 추적이 있어야 신뢰.
- (자백 2) 잡코리아 단일칸 압축이 실제 잡코리아 검색에서 0건을 안 만드는가(괄호/연산자 유출 의심).
- (자백 3) 사람인 필드 분배가 실제 사람인 필터칸 이름/동작과 맞는가(가정만 하고 라이브 미확인일 위험).
- (자백 4) 3단/완화가 무한반복·native 필터 충돌·종료조건 누락을 만들지 않는가.

---

## 적대 검증 로그 (비워둠 — 작업 중 채움)

| 역할 | 판정 | 근거(재현 명령/경로) | 날짜 |
|---|---|---|---|
| G (생성자) | — | — | — |
| V1 (Codex fresh) | — | — | — |
| V2 (Claude 리셋) | — | — | — |
| T (기계: pytest/verify) | — | — | — |

---

## 다음 세션이 붙여넣을 한 줄 트리거(예)
> "/st 다음 goal 문서 `docs/engineering/linkedin-boolean-live-wire-goal-2026-06-24.md` 읽고,
>  **슬라이스 A(검색 의도→라이브 keyword_plan 주입 + 채널 렌더러: 사람인 필드분배 / 잡코리아 단일칸 / 링크드인 boolean)**부터 worktree 파서 진행해."
