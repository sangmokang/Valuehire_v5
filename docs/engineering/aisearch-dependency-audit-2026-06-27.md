# aisearch 의존성 전수 조사 + `.claude` 이사 지도 (2026-06-27)

> 목적 두 가지: (1) `.claude/skills/aisearch`의 **모든 의존성을 전수 조사**해 무엇이 폴더 밖/레포 밖을 가리키는지 박제한다. (2) 사장님이 정한 장기 방향 — **레포 `skills/` 내용을 전부 `.claude`에서 동작** — 의 **이사 설계도**로 쓴다.
>
> 조사 방법: 4개 독립 에이전트 병렬 감사 + 1개 적대검증자(V1). 모든 항목은 `file:line`·`git ls-files`·`grep` 실측 기반.

---

## 0. 한눈 요약

| 구분 | 결과 |
|---|---|
| aisearch가 가리키는 참조 | 총 22건 (folder-internal 4 · repo-internal-shared 14 · repo-external-HOME 4) |
| **이번에 끊은 진짜 위험** | 레포 밖·git 미추적 HOME 참조 **3건**(codex 스크립트·codex 미러·linkedin-rps 문서) |
| 조치 | 그 3건을 `.claude/skills/aisearch/vendor/`로 **들여옴(vendoring)** + 자립 게이트 추가 |
| 검증 | `vendor/check_self_contained.py` → `status=OK` / 무결성 테스트 6 passed 회귀 0 / 공유 자산 무삭제 |
| 장기 이사 최대 함정 | `.gitignore:19 .claude/` (옮기면 git에서 소실) + `tools/multi_position_sourcing` 25개 테스트 결합 |

---

## 1. aisearch 폴더가 가리키는 모든 참조 (전수)

감사 대상: `.claude/skills/aisearch/SKILL.md`, `.claude/skills/aisearch/candidate-output-contract.json`.

원칙적으로 이 스킬은 **"정본은 레포에 있고 복제 금지"** 를 지켜 알맹이를 `docs/sot/*`·`tools/multi_position_sourcing/`·`skills/search|multisearch/`에 위임한다. 그 repo-internal 타깃은 **전부 존재 + git 추적됨 → 안전.** 위험은 폴더 밖 HOME 참조뿐이었다.

| Target | Where (line) | klass | exists | git_tracked | note |
|---|---|---|---|---|---|
| candidate-output-contract.json | SKILL 91,116 | folder-internal | yes | no | 폴더 내부 유일 정본인데 `.claude/` 미추적 → 유실/드리프트 위험(이사 대상) |
| CLAUDE.md | SKILL 17 | repo-internal-shared | yes | yes | 루트 SOT |
| docs/harness.md | SKILL 18 | repo-internal-shared | yes | yes | 작업 루프 |
| docs/sot/ (dir) | SKILL 19,46 | repo-internal-shared | yes | yes | 디렉터리 |
| docs/sot/22-talent-search-filters.md/.json | SKILL 46,110; JSON 18 | repo-internal-shared | yes | yes | 필터 SOT |
| docs/sot/23-channel-dom-selectors.md | SKILL 46,110 | repo-internal-shared | yes | yes | DOM 셀렉터 |
| docs/sot/24-position-jd-sot.json | SKILL 73,111 | repo-internal-shared | yes | yes | JD 평가 |
| docs/sot/25-ai-search-execution-process.md/.json | SKILL 39,49,109 | repo-internal-shared | yes | yes | 한 턴 실행 권위 |
| docs/sot/26-portal-login-spec.json | SKILL 112 | repo-internal-shared | yes | yes | 포털 로그인 |
| tools/multi_position_sourcing/ | SKILL 20,47,86,115 | repo-internal-shared | yes | yes | 실행 엔진 |
| skills/search/SKILL.md | SKILL 49,85,113 | repo-internal-shared | yes | yes | 단일 포지션 로직 |
| skills/search/references/ (6개 .md) | SKILL 113 | repo-internal-shared | yes | yes | 전부 확인됨 |
| skills/multisearch/SKILL.md | SKILL 86,114 | repo-internal-shared | yes | yes | 다중/복구 |
| tests/test_skill_reference_integrity.py | SKILL 8(과거) | repo-internal-shared | yes | yes | 정본 무결성 지킴이 |
| env VALUEHIRE_SEARCH_LIST_DISCORD_WEBHOOK_URL | JSON 7,38; SKILL 96 | repo-internal-shared | yes | no | `.env.local:34`에 존재(미추적은 정상 — 비밀값) |
| Discord channel_id 1470955309089554554 | JSON 5 | folder-internal | yes | no | #ai_search 리터럴 |
| Discord guild_id 834329924486823947 | JSON 6 | folder-internal | yes | no | 길드 리터럴 |
| 공개 profile URL 템플릿(linkedin/jobkorea/saramin) | JSON 18 | folder-internal | yes | no | 외부 웹 엔드포인트 템플릿 |
| Valuehire_v4 | SKILL 3,57 | (부정 참조) | no | no | **의존 아님** — "v4 코드·npm 금지" 금지 대상 |
| ~/.codex/skills/ai-search | SKILL 3,8(과거) | repo-external-HOME | yes | no | codex 쌍둥이 미러 |
| ~/.codex/skills/ai-search/scripts/ai_search_sot_check.py | SKILL 43(과거) | repo-external-HOME | yes | no | **실행 명령이 레포 밖·미추적 → 클린 체크아웃에서 깨짐** |
| ~/.claude/skills/linkedin-rps-jd-set-builder/SKILL.md | SKILL 87,117(과거) | repo-external-HOME | yes | no | RPS JD 레인, HOME·미추적 |

> "(과거)"는 이번 조치(옵션 A) **전** 라인 번호. 조치 후 SKILL.md는 vendor/ 경로를 가리킨다(§3).

---

## 2. 이번에 적용한 조치 — 옵션 A (aisearch 자립화)

레포 공유 자산(엔진·SOT·형제 스킬)은 **옮기지 않고**(25개+ 소비자 파손 방지), 레포 밖·git 미추적 HOME 참조 3건만 폴더 안으로 들여왔다.

들여온 것(`/Users/kangsangmo/Valuehire_v5/.claude/skills/aisearch/vendor/`):
- `ai_search_sot_check.py` ← `~/.codex/skills/ai-search/scripts/ai_search_sot_check.py` (표준 라이브러리 + `--repo` 인자만 — codex 폴더 의존 0, 그대로 동작)
- `linkedin-rps-jd-set-builder.md` ← `~/.claude/skills/linkedin-rps-jd-set-builder/SKILL.md`
- `SOURCES.json` — 위 두 파일의 원본 경로·복사 시점·sha256(드리프트 감지용 기능 메타데이터)
- `check_self_contained.py` — **자립 게이트**: SKILL.md에 `~/.codex`·다른 `~/.claude/skills` 참조 0건 + vendor 파일 완비를 강제(exit 0/1)

### 검증 증거 (fresh)
- RED: 조치 전 `check_self_contained.py` → `status=FAIL` (SKILL.md 라인 3·8·43·87·117 외부 참조 5건), exit=1
- GREEN: 조치 후 → `status=OK aisearch self-contained (HOME 외부 의존 0, vendor 파일 완비)`, exit=0
- 들여온 SOT 체커 동작: `python3 .claude/skills/aisearch/vendor/ai_search_sot_check.py --repo …` → `status=OK`, 10단계 stage_ids 정상 출력
- 회귀 0: `pytest tests/test_skill_reference_integrity.py` → 6 passed
- 공유 자산 무삭제: docs/sot/22·25, tools/multi_position_sourcing, skills/{search,multisearch,humansearch,position-registration} 전부 OK
- V1 적대검증: "살아있는 HOME 런타임 참조 0건" 독립 확인(REFUTE on 잔존 의존 주장)

### 왜 무결성 테스트(git 추적)에 aisearch를 안 넣었나
`.claude/`는 `.gitignore:19`로 미추적이다. git 추적 테스트가 `.claude/...` 존재를 단언하면 **클린 체크아웃/CI에서 그 파일이 없어 또 깨진다**(지금 고치려던 바로 그 병). 그래서 자립 검사는 **폴더 안 로컬 스크립트**(`vendor/check_self_contained.py`)로 둔다.

---

## 3. 레포 `skills/` 인벤토리 + 외부 의존 (장기 이사 대상)

`/Users/kangsangmo/Valuehire_v5/skills/` = 4개 스킬, **전부 git-tracked(12파일)**. 4개 모두 자기 폴더 밖을 강하게 참조 → `skills/`만 `.claude`로 옮기면 깨진다.

| 스킬 | git-tracked 파일 | 정체 | 핵심 외부 의존 |
|---|---|---|---|
| **search** | SKILL.md, README.md, references/*.md ×6 (총 8) | 단일 포지션 AI Search 핵심 판단 로직 | docs/sot/22, tools/multi_position_sourcing/{llm_keywords,portal_queue_executor,models}.py, HOME ~/.hermes, .env.local |
| **multisearch** | SKILL.md (1) | 다중 포지션 포털 소싱 레이어 | docs/sot/22, docs/search-access.md, docs/ai-search/…, **skills/search(형제)**, tools/multi_position_sourcing/*.py(~20), HOME ~/.valuehire/portal_profiles·Keychain·.env.local |
| **humansearch** | SKILL.md, humansearch.config.json (2) | 사람 검색결과 순회→채점→Discord | CLAUDE.md, docs/harness.md, docs/sot/, tools/multi_position_sourcing/{humansearch,raw_cdp,discord_briefing,scoring}.py, HOME ~/.vh-search-results |
| **position-registration** | SKILL.md (1) | JD→ClickUp 포지션 등록(dry-run) | CLAUDE.md, docs/harness.md, docs/sot/, tools/multi_position_sourcing/{position_registration,request_parser,posting_*,position_dedup,access}.py |

소비자(누가 `skills/<name>`를 참조하나): search 13 · multisearch 5 · humansearch 3 · position-registration 3.

---

## 4. 공유자산 영향범위 — `.claude` 이사 시 깨지는 곳 (블라스트 반경)

### (1) `tools/multi_position_sourcing/` = 가장 강한 결합
Python 패키지 import 경로로 **테스트 25개**(test_multi_position_sourcing, test_reservoir_*, test_channel_search_*, test_humansearch_skill …)에 묶임. `.claude/` 아래로 옮기면 sys.path/패키지 경로 붕괴 → **25개 일괄 ImportError**. → 엔진은 레포에 두고 경로 문자열만 갱신하는 게 안전.

### (2) `tests/test_skill_reference_integrity.py` 하드코딩 경로 (즉시 깨짐)
| line | 내용 |
|---|---|
| 7 | `REPO = Path(__file__).resolve().parent.parent` |
| 8 | `CODEx_AI_SEARCH = Path.home()/".codex"/"skills"/"ai-search"` (HOME) |
| 9 | `CLAUDE_SKILLS = Path.home()/".claude"/"skills"` (HOME) |
| 11-15 | `REPO_SKILL_DIRS = (REPO/"skills"/"search", …/"multisearch", …/"position-registration", …/"humansearch")` |
| 44-49 | `REPO/"skills/search/references/*.md"` 6개 존재 단언 |
| 53 | `REPO/"skills/humansearch/humansearch.config.json"` |
| 72 | 절대경로 `"/Users/kangsangmo/.codex/skills/ai-search/SKILL.md"` 하드코딩(타 PC 비결정) |
| 92-96 | `~/.claude/skills/{talent-search,saramin,jobkorea,linkedin-rps-jd-set-builder}/SKILL.md` 실제 존재 단언 |

### (3) `.gitignore:19 .claude/` = 이사 핵심 함정
현재 `.claude/` 추적 0건, `skills/` 추적 12건. 추적 파일을 `.claude/`로 옮기면 **git이 조용히 untracked 처리 → CI·타 PC에서 공유자산 소실.** 이주하려면 반드시:
1. `.gitignore`에 부정 규칙(`!.claude/skills/`, `!.claude/skills/**`) — 상위 ignore 시 중간 경로까지 모두 un-ignore해야 동작, 또는
2. `git add -f` 강제 추적(이후에도 ignore 경고 지속, 비권장).

### (4) docs/sot/22-26
SOT 본문 6파일 외 소비자 7개(goal 문서 3 + skills 3 + 무결성 테스트 1). 이번 이사 대상은 `skills/`이지 `docs/sot/`가 아니므로 **SOT 경로를 유지하면 이 축 영향은 작다**(스킬 본문의 SOT 경로 문자열만 갱신).

---

## 5. 장기 이사 체크리스트 (승인 후 별도 진행)

`skills/` → `.claude/skills/` 이사를 안전하게 하려면 **한 묶음으로** 수정:
1. **`.gitignore`**: `.claude/skills/` 부정 규칙 추가(이게 안 되면 옮긴 파일이 git에서 사라짐 — 0순위).
2. **`tests/test_skill_reference_integrity.py`**: 11-15·44-53행 `REPO/"skills/…"` → 새 경로, 72·92-96행 절대/HOME 경로는 fixture/env로 추상화.
3. **각 SKILL.md 본문**: `tools/`·`docs/`·형제 스킬 상대경로 문자열 전부 갱신.
4. **형제 동반 이주**: multisearch → search 직접 참조라 함께 옮긴다.
5. **`tools/multi_position_sourcing`는 레포 유지**(또는 패키지 경로 전면 재배선 — 25개 테스트 영향). 권장: 엔진은 레포, 스킬만 `.claude`.
6. **HOME 런타임/Keychain 경로**(~/.valuehire, ~/.vh-search-results, .env.local)는 절대경로라 그대로 동작 — 단 `.claude` 스킬에서도 동일 경로 쓰는지 확인.
7. 이주 후 `./verify.sh` 초록 + 각 스킬 트리거 실발동 확인.

> 결론: **이사는 단순 `mv`가 아니라 "gitignore 예외 + 테스트 경로 + 스킬 본문 경로"를 동시에 푸는 마이그레이션.** aisearch 자립화(§2)는 그 1단계가 이미 끝난 상태다.

---

## 6. 적대검증(V1) 판정 — 자립화 결과

- (b) 오분류 REFUTE: 감사자가 "HOME 런타임 참조 3건"이라 본 SKILL.md 43·87·117은 **이미 vendor 경로**(`.claude/skills/aisearch/vendor/…`). HOME 잔존은 line 8 산문의 "HOME에 의존하지 않는다"는 부정 진술 + `SOURCES.json`의 origin 메타데이터뿐(런타임 아님).
- (a) 누락 외부 참조: 없음(PASS). 살아있는 HOME 런타임 참조 0건.
- (c) 잘못된 "shared" 분류: 없음(PASS). repo-internal 타깃 전부 존재+추적.
- (d) git_tracked: aisearch 6파일 전부 `.gitignore:19`로 미추적(`git ls-files` 0건) — 이건 결함이 아니라 `.claude` 설계 특성(이사 대상).
- 독립 재현: `check_self_contained.py status=OK`, `ai_search_sot_check.py exit=0`.
