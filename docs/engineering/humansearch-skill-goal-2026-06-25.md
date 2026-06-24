# Goal Prompt — `humansearch` 스킬 만들기 (2026-06-25)

> 모드: **noncode-planning (스펙/설계서)** · 위험등급: **이 문서 L1** / **스킬이 부르는 행위는 L3**
> (자동 로그인·프로필 순회·스크린샷·Discord 발송 = 되돌리기 영향 있는 외부 행위 → 구현 단계는 L3 풀하네스)
> 적용 SOT: `CLAUDE.md`(루트), `docs/harness.md`, `docs/sot/22-talent-search-filters.json`, `docs/sot/23-channel-dom-selectors.md`
> 스킬 도메인 절차: `skill-creator`(로드 완료) — 구조·description·평가는 skill-creator, 검증은 `/st`.

---

## 0. 한 줄 정의 (사람 말)

> 사장님이 채용 사이트(링크드인 RPS·사람인·잡코리아)에 **검색을 직접 걸어두고** 포지션명을 주거나
> 화면에 포지션이 분명히 보일 때, **리스팅(목록) 페이지를 한 장씩 넘기며 후보를 하나씩 열어
> 스크린샷으로 저장 → JD와 점수 매김 → 합격선 넘는 후보만 한꺼번에 Discord `#ai_search` 로 보내는** 스킬.

핵심 차별점: 기존 `search`/`multisearch`는 **스킬이 검색어를 만들어 검색까지** 한다.
`humansearch`는 **사람이 이미 걸어둔 검색 결과 화면을 그대로 받아** 순회·채점·발송만 한다(human-driven).

---

## 1. 현재 상태 — 이미 있는 것 vs 새로 만들 것 (과거 회수, file:line)

### 이미 있음 → **재사용**(중복 구현 금지)
| 자산 | 경로 | 무엇을 주는가 |
|---|---|---|
| Discord 후보 브리핑 포맷 | `tools/multi_position_sourcing/discord_briefing.py:12` | 사장님이 요청한 출력(Profile URL·점수·요약·잘맞음·안맞음·근거)을 **그대로** 출력 |
| 후보 데이터 모델 | `tools/multi_position_sourcing/models.py` `PositionMatch` | `candidate_url, score, why_fit, why_not, profile_summary, position_id, evidence_paths` |
| 채널 라우팅·권한 | `tools/multi_position_sourcing/discord_routing.py:21` | `saramin / jobkorea / linkedin_rps / public_web` 라우팅 + 권한 게이트 |
| 필터·제외·점수 SSOT | `docs/sot/22-talent-search-filters.json` | 프리랜서 제외 마커, 이직잦음 판정식, 학력 체크박스, 채널별 결과수 판단 트리, 봇 가드 |
| DOM 셀렉터 SSOT | `docs/sot/23-channel-dom-selectors.md` | evidence-first(행동 전 DOM 덤프), 채널별 셀렉터 |
| LinkedIn open-to-work·학교 후처리 | SOT22 `channels.linkedin` | `result_profile_links`, `education_school` 후처리 필터, 봇 딜레이 20~60초 |
| 출력 계약(메모리) | `memory/ai-search-candidate-output-contract.md` | 후보는 항상 JSON(profile_url·score·why_fit·summary), `#ai_search` 전송 |

### 새로 필요 → **구현 대상**(humansearch만의 신규)
1. **리스팅 순회기**: 사람이 연 검색 결과 URL에서 목록 카드 → 다음 페이지(`start=25` 식 PAGINATION) 순회.
2. **랜덤 1건씩 클릭**(LinkedIn open-to-work 우선) + **프로필 단위 스크린샷 저장**.
3. **채널별 채점 루브릭 적용**(아래 §3 계약) → `PositionMatch` 로 환원.
4. **합격 후보 묶음 발송**: 여러 `PositionMatch` 를 한 번에 `#ai_search` 로(기존 briefing 재사용).
5. **SKILL.md** + 설정 JSON(`humansearch.config.json`) + 스킬 계약 테스트.

> ⛔ 비대상(이미 있어서 다시 만들지 않음): 검색어 생성·필터 입력·DOM 셀렉터 표·프리랜서/이직 제외 로직 정의·Discord 포맷.
> humansearch는 이것들을 **호출**한다.

---

## 2. 입력 계약 (스킬을 어떻게 깨우나)

```json
{
  "$contract": "humansearch.input",
  "trigger_keywords": ["humansearch", "휴먼서치", "이 화면 순회", "후보 솎아서 디스코드", "리스팅 돌면서 채점"],
  "invocation": {
    "mode": {
      "by_position_name": "사장님이 포지션명(또는 ClickUp positionId)을 줌 → 해당 JD 로드",
      "by_visible_screen": "현재 브라우저에 포지션·검색결과가 명확히 보임 → 그 화면을 SOT 삼음"
    },
    "required_one_of": ["position_name", "position_id", "visible_search_url"],
    "channel": {
      "type": "enum",
      "values": ["linkedin_rps", "saramin", "jobkorea"],
      "infer_from": "활성 탭 URL (talent pool URL 패턴 매칭) 또는 사장님 지정",
      "execution": "병렬 허용 — 채널별 세션 충돌·봇 가드 안전하면 3채널 동시. 위험 감지 시 순차 폴백 (사장님 확정 2026-06-25)"
    },
    "search_already_set_by_human": true,
    "traversal": {
      "max_pages": 10,
      "page_order": "랜덤 — start=0,25,50… 페이지를 무작위 순서로 오감 (순차 PAGINATION 패턴 회피)",
      "human_like_pacing": "프로필·페이지 열 때 너무 빠른 속도 금지. 사람처럼 천천히 (사장님 확정 2026-06-25)",
      "delay_ref": "LinkedIn 은 SOT22 bot_protection 20~60초 랜덤 준수, 사람인·잡코리아도 카드 간 충분한 간격"
    },
    "jd_source": {
      "if_position_id": "ClickUp JD 자동 fetch (기존 ai-search-position-pipeline 경로 재사용)",
      "if_visible_only": "화면에 보이는 포지션 컨텍스트 + 사장님 1줄 요약"
    }
  },
  "preconditions": [
    "사장님 계정이 해당 채널 인재DB 라이선스 보유(R4)",
    "사장님이 검색 필터를 이미 걸어 결과 목록이 보이는 상태",
    "사장님 chrome 점유 중이면 자동 액션 0 — 손 뗄 때까지 양보(R4 자동재개)"
  ]
}
```

---

## 3. 채점 계약 (채널별로 다름 — 사장님 지시 그대로)

### 3-1. LinkedIn (가중 점수제, open-to-work 우선)
```json
{
  "$contract": "humansearch.scoring.linkedin",
  "candidate_pool": "Open to work 위주 (Spotlight 'Open to work' 508명 류)",
  "selection": "랜덤값 부여 후 하나씩 클릭 (순서 무작위화 = 봇 패턴 회피 겸 편향 방지)",
  "per_profile_action": ["프로필 상세 진입", "화면 스크린샷 1장 저장", "레쥬메 텍스트 추출"],
  "rubric_weights": {
    "education": 0.30,
    "role_fit": 0.50,
    "profile_text_logic": 0.10,
    "job_stability": 0.10
  },
  "rubric_detail": {
    "education": "학력 — 학교/학위가 JD 기대에 부합",
    "role_fit": "직무 적합성 — JD 핵심 책무·기술과 직결 (최대 가중)",
    "profile_text_logic": "프로필 텍스트 정리·논리력 — 서술이 정돈·일관",
    "job_stability": "이직 안정성 — 잦은 단기 이직이 적을수록 가점"
  },
  "score_range": "0~100 (가중합 → 100점 환산)",
  "pass_threshold": 70
}
```

### 3-2. 사람인 · 잡코리아 (하드 제외 우선 + 채점)
```json
{
  "$contract": "humansearch.scoring.saramin_jobkorea",
  "hard_exclude_before_scoring": {
    "freelancer": {
      "rule": "프리랜서/개인사업자/외주 마커 포함 시 제외",
      "markers_source": "SOT22 candidate_quality_filters.freelancer.markers",
      "markers": ["freelance","freelancer","프리랜서","개인사업자","independent","외주","Contract Worker"]
    },
    "low_tier_school": {
      "rule": "전문대 + 하위권 대학 + 일반 지방 사립 제외. 단 지방 국공립대는 허용(통과)",
      "decided_2026-06-25": "사장님 확정 — 지방 국공립대 OK. memory/education-tier-screening 와 일치: 인서울·지방 국공립·단국대 이상만 통과, 전문대·하위권·일반 지방사립 제외"
    },
    "frequent_job_change": {
      "rule": "재직 12개월 미만 단기 근무가 다수(2회+) 있는 회사 경력 → 프로필 통째 제외(아예제외)",
      "logic_source": "SOT22 candidate_quality_filters.frequent_job_change",
      "logic": "careerPath.filter(j => months(j)<12 && within5y(j.end)).length >= 2"
    }
  },
  "after_exclude": "남은 후보만 채점. 채점 루브릭 = LinkedIn 과 동일(학력0.30/직무0.50/논리0.10/이직안정0.10) — 사장님 확정 2026-06-25",
  "pass_threshold": 70,
  "result_count_decision_tree": "SOT22 channels.<ch>.result_count_decision_tree 그대로(0~4 포기 / GOLD 전수 / 81~300 상위 40 / 300+ 키워드 추가)"
}
```

---

## 4. 출력 계약 (Discord `#ai_search` 묶음 발송)

```json
{
  "$contract": "humansearch.output",
  "reuse": "tools/multi_position_sourcing/discord_briefing.py format_discord_candidate_briefing()",
  "per_candidate_model": "PositionMatch",
  "fields": {
    "candidate_url": "프로필 URL — 절대 오류 없어야 함(R: URL 무결성 검증 필수)",
    "score": "매칭 점수 0~100",
    "profile_summary": "학력·경력 사항 요약",
    "why_fit": "JD와 잘 맞는 부분(불릿)",
    "why_not": "JD와 안 맞는 부분(불릿)",
    "evidence_paths": "스크린샷·레쥬메 저장 경로(근거)"
  },
  "batch": "여러 후보를 한 메시지/연속 메시지로 #ai_search 채널에 한꺼번에 발송",
  "url_integrity_gate": {
    "rule": "발송 전 모든 candidate_url 을 실제 접근 가능 형태로 검증 — 깨진/상대경로/javascript:void URL 발송 금지",
    "why": "사장님 0순위 요구 '프로필 url 절대 오류 없어야 할 것'",
    "linkedin_normalize": "SOT22 linkedin.result_profile_links 패턴 / saramin·jobkorea url_normalize 규칙 재사용"
  },
  "send_gate": "후보 브리핑 '발송'은 자동 OK(정보 전달). 단 '제안·메일 보내기'(R3)는 절대 자동 금지 — humansearch 범위 밖"
}
```

---

## 5. 안전·SOT 불변식 (스킬 동작 중 항상)

```json
{
  "$contract": "humansearch.safety",
  "invariants": [
    "R: 3사 자동 로그인 막지 않음(SOT 1)",
    "R: 사장님 chrome 점유 시 즉시 양보 → 손 떼면 자동 재개(SOT 2 / R4). 봇처럼 창 여닫기·URL 연타·알람 후 무한재시도 금지",
    "R: 제안·메일 '보내기' 자동 클릭 금지(SOT 3). humansearch는 '후보 브리핑'만 발송",
    "R: 캡차/봇차단/로그인 리다이렉트 감지 시 즉시 STOP, retry 금지(SOT22 R2)",
    "R: 채널을 직무로 가르지 않음(SOT22 R5)",
    "R: 행동 전 DOM 덤프 — 셀렉터 추측이 fresh 덤프를 못 이김(SOT23 evidence-first)",
    "R: LinkedIn 키워드/프로필 간 20~60초 랜덤 딜레이(SOT22 linkedin.bot_protection)"
  ]
}
```

---

## 6. 인수 기준 (게이트 4에서 판정)

**기계 단언(`./verify.sh` 스킬 계약 테스트):**
- [ ] `humansearch` SKILL.md frontmatter `name`/`description` 존재 + 트리거 키워드(§2) 포함.
- [ ] `humansearch.config.json` 이 §3·§4 계약 스키마를 만족(필수 키 존재, 가중치 합=1.0).
- [ ] 출력 후보 객체가 `PositionMatch` 필드 6종을 모두 채움(빈 `candidate_url` 금지).
- [ ] URL 무결성 함수: 깨진/상대/`javascript:void` URL 입력 시 reject 하는 테스트 GREEN.
- [ ] 채널별 하드 제외(프리랜서·이직잦음) 픽스처 입력 시 제외되는 테스트 GREEN.

**판단 단언(게이트 4b 적대검증):**
- [ ] 실제 발동 문장으로 스킬이 **뜨는가**(트리거=배선, R4) — `search`/`multisearch`와 오발동 충돌 없는가.
- [ ] LinkedIn 가중치(30/50/10/10)가 산출 점수에 실제 반영되는가(가중치 mutant 1개 → 점수 바뀌어야).
- [ ] 사람인/잡코리아 제외 규칙이 채점 **전에** 걸러지는가(제외 대상이 점수만 낮게 통과되지 않는가).

---

## 7. 결정 사항 (사장님 확정 2026-06-25 — 스펙 확정됨)

- **Q1 합격선 → 70/100.** 70점 이상만 Discord `#ai_search` 발송.
- **Q2 학력 컷 → 지방 국공립대 허용.** 전문대·하위권·일반 지방 사립은 제외. (memory/education-tier-screening 와 일치)
- **Q3 사람인/잡코리아 점수식 → LinkedIn 과 동일 4-가중치**(학력0.30/직무0.50/논리0.10/이직안정0.10). 단 하드 제외(프리랜서·이직잦음·하위학교)는 채점 전에 먼저 적용.
- **Q4 채널 실행 → 병렬 허용.** 세션 충돌·봇 가드 안전하면 3채널 동시, 위험 감지 시 순차 폴백.
- **Q5 페이지 순회 → 약 10페이지, 랜덤 순서로 오감, 너무 빠른 속도 금지(사람처럼).**

---

## 8. 적용 게이트 (구현 시 — harness.md)

게이트 0(과거 회수 ✅ 이 문서) → 0.5 워크트리(`make task NAME=humansearch-skill`)
→ 1 스펙(이슈 + 위 인수 기준) → 2 RED(스킬 계약 테스트 실패 먼저)
→ 3 구현(SKILL.md + config + 순회기) → 4a `./verify.sh` exit 0 + 4b 자기 적대검증 → Codex Rescue 2차
→ 5 `make ship`(PR, CI 초록+merge) → 6 종료.

## 9. 비범위 (이번에 안 함)
- 검색어 생성·필터 자동 입력(= `search`/`multisearch` 책임, 그대로 둠).
- 제안/InMail/메일 발송(= R3, 사람 수동 게이트).
- 새 DOM 셀렉터 표 작성(= SOT23 재사용, 바뀌면 런타임 덤프).

## 10. 적대 검증 로그 (G → V1 → V2, 3자 일치)

장부 원본: `docs/engineering/humansearch.verdict.json`

| 결함 | 심각도 | G(생성) | V1(codex) | V2(리셋) | 처리 |
|---|---|---|---|---|---|
| URL 공백·invalid 발송 | CRITICAL | 미검출 | 발견 | 확인 | fix: 공백 전면거부 + `eligible_matches_for_send` 발송 관문 |
| 프리랜서 공백 우회 | HIGH | 미검출 | 발견 | 확인 | fix: collapsed 매칭 |
| 저티어 사립 미감지 | HIGH | 의도 | 발견 | 타당 인정 | wontfix(의도) — 기계는 명시마커만, 미세등급은 사람/LLM. 테스트로 의도 고정 |
| 반올림 합격선 부풀림 | MEDIUM | 미검출 | 발견 | 확인 | fix: round-once |
| 제로폭 URL 통과 | (edge) | 미검출 | 미검출 | **V2 발견** | fix: 제어/포맷문자 거부 |
| 전각 freelance | (edge) | 미검출 | 미검출 | **V2 발견** | fix: NFKC 정규화 |

- 자기 적대검증(G): mutant 5종(임계값·제외컷·URL·send-gate·round) 일부러 깨 → 테스트 전부 검출 → 복원 GREEN.
- V1 증거는 G가 올바른 시그니처로 직접 재현(codex 자체 하네스의 시그니처 오류는 무효 처리).
- V2 증거도 G가 직접 재현(ZWSP→거부, %20·한글IDN→통과 유지=과잉거부 없음, 전각→제외).
- 최종: `pytest tests/ -q` → **589 passed, 5 subtests passed**. three_way_agree=true.
- 배선(R4): 스킬은 human-driven(자동 cron 호출부 없음이 정상). 발송 게이트는 SKILL.md output 절차에 명시.
- 트리거(R6): description 에 트리거 문장 포함, search/multisearch 와 목적 구분 명시 → 오발동 충돌 없음(V1 (f) 확인). 실발동 자동측정 도구 없음 → 그 부분은 수동 판정.
