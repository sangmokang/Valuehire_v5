# CLAUDE.md — Valuehire v5 최상위 규칙 (SOT)

> 이 문서가 제일 위다. 다른 문서·습관·플러그인 지침보다 먼저 따른다.
> 여기 적힌 것은 **약화 금지**. 나머지는 필요할 때 찾아 읽는다.

---

## 1. 말하기 — 사장님께 보고할 때 (매 턴 적용)

**한국어로, 쉽게, 짧게.** 사장님은 코드 전문가가 아니다.

- 기술 용어·영어 약자·내부 절차명(RED/GREEN, worktree, verdict, 게이트 번호, 파일:줄번호)을 그대로 쓰지 않는다.
- 꼭 필요하면 괄호로 쉬운 한 줄을 붙인다.
- 말할 내용은 셋뿐: **무엇을 했나 / 왜 / 다음에 뭘 하나.**

| ✗ | ✓ |
|---|---|
| "verify exit 0, 393 passed" | "검사 393개 전부 통과했습니다." |
| "worktree에서 RED→GREEN 후 ship" | "따로 작업방 만들어 고치고 올렸습니다." |
| "PR mergeable, CI green" | "합쳐도 되는 상태입니다. 검사도 통과했고요." |

- 중간·차단 보고: 1~3문장(상태/이유/다음).
- 최종 보고: `AGENTS.md`의 5칸 형식.
- 톤: 합쇼체, 짧게, 이모지·느낌표 남발 금지.

---

## 2. SOT 불변식 — 절대 금지선 (fail-closed · 어길 수 없음)

| # | 규칙 | 어기면 |
|---|---|---|
| **A** | **3사(사람인·잡코리아·링크드인) 자동 로그인을 막지 않는다.** 저장된 자격증명으로 항상 자동 로그인·재로그인. 사람에게 넘기는 건 2FA·캡차·체크포인트가 실제로 뜬 순간뿐이고, 그때는 브라우저 창을 앞으로 띄운다. 자동 로그인을 막는 코드·규칙은 발견 즉시 삭제. | SOT 위반 → `docs/sot/26-portal-login-spec.json` |
| **B** | **사장님이 크롬에서 3사 화면을 만지면 그 머신만 잠깐 양보, 60초 조용하면 자동 재개.** 유튜브 등 다른 화면은 개입 아님. 무기한 중단·작업목록 폐기·10분 이상 고정 대기는 SOT 위반. 로그인은 최우선. | SOT 위반 → `docs/sot/29-fleet-control.md` INV9 |
| **C** | **자동 발송은 게이트 전부 통과 시에만.** 85점↑ + 하드제외 없음 + precheck 통과 + 글자수 캡 + 90일 중복 아님 + 일일 상한 미만 + 킬스위치 꺼짐. 하나라도 어긋나면 발송 안 함. 단, 사장님이 특정 건을 "보내라"고 직접 지시하면 초안에서 멈추지 않고 Send까지 누른다. | SOT 위반 → `docs/sot/28-auto-send-policy.json` |
| **D** | **봇처럼 굴지 않는다.** 창 열고 닫기 반복, URL 연속 입력, 실패 후 같은 시도 무한 반복 금지. 막히면 원인을 해결하고 사람처럼 움직인다. | 계정 정지 위험 |
| **E** | **`main`에 직접 쓰지 않는다.** 모든 변경은 `make task NAME=...` 로 판 작업방(worktree)에서. | 게이트 위반 |
| **F** | **증거 없이 "됐다"고 하지 않는다.** 완료 = 검사 통과 + 프로덕션 경로에 실제로 연결됨 + 실물 1건. "should/probably/될 겁니다" 금지. | 게이트 위반 |

---

## 3. SOT 불변식 — 내가 만든 코드는 믿지 않는다 (두 번 깐다)

내 코드는 늘 헛점이 있다고 전제한다. **내가 만든 것을 믿지 않는다.**

1. **작은 기능 단위로 만든다** — 인수 기준 1개 = 작업방 1개. 큰 덩어리를 한 번에 만들지 않는다.
2. **시작 전에 과거를 찾는다** — 메모리·기존 코드·스킬/문서 3축을 먼저 뒤진다. 이미 있으면 새로 만들지 말고 확장한다.
3. **내가 먼저 깬다** — 빈 값·잘못된 입력·경계값·429/캡차·중복·동시성·비밀키 노출을 일부러 넣어본다.
4. **Codex Rescue가 또 깬다** — 다른 도구로 같은 코드를 독립 공격. "PASS"만 오면 무효, 반증 시도 본문이 있어야 인정.
5. **둘 다 못 깨야 통과.** 그제야 사장님께 가져간다.

절차 전문: `docs/harness.md`. 엄격 모드 발동 시: `~/.claude/skills/strict/SKILL.md`.

---

## 4. 작업 루프 — 게이트와 명령

| 게이트 | 할 일 | 명령 |
|---|---|---|
| 0 | 미해결 RED 없나 + 깨끗한 컨텍스트인가 | `make red-ledger` |
| 0.5 | 과거 지시 회수 (메모리·코드·문서 3축) | `git log --grep=`, `grep -ri docs/ tools/` |
| 1 | 이슈 + 인수 기준 1개(기계 단언 우선) | `gh issue create` |
| 2 | 작업방 파고 **실패하는 검사 먼저** 커밋 | `make task NAME=<slug>` |
| 3 | RED→GREEN 최소 변경 (파일 1~5 / 50~300줄) | — |
| 3.5 | **배선 증명** — 프로덕션 진입점에서 새 코드까지 호출 경로 추적. 테스트만 import = 고아 = 미완료 | 동적 경로는 grep 금지, 실행 로그로 |
| 4a | 검사 실행, 숫자 그대로 기록 | `./verify.sh` (exit 0 == 통과) |
| 4b | 2패스 적대검증 (내가 → Codex Rescue) | `/codex:rescue` |
| 5 | 올리기 → PR → CI 초록 + merge 전까지 "완료" 없음 | `make ship` |
| 6 | merge 후 작업방 정리 + `/clear` | `git worktree remove` |

**진화 규칙:** 게이트를 통과했는데 나중에 결함이 새어나오면, 그 결함을 잡는 검사를 **먼저 추가**(RED)한 뒤 고친다. 4b에서 반복되는 지적은 4a 기계검사로 승격한다.

---

## 5. 저장소 지도 (어디에 뭐가 있나)

| 경로 | 내용 |
|---|---|
| `tools/multi_position_sourcing/` | **핵심 엔진.** 포털 로그인·수집·매칭·발송·함대가 전부 여기 있다 |
| ↳ `portal_login.py` `portal_autologin.py` | 3사 로그인 수행 (규칙 A의 구현체) |
| ↳ `session_guard.py` | 세션 유지 + 사장님 점유 감지·양보 (규칙 B의 구현체) |
| ↳ `login_barrier.py` | 로그인을 **하지 않는다** — "로그인했다"는 주장을 영수증 파일로 검증하는 fail-closed 게이트 |
| ↳ `raw_cdp.py` `humansearch_cdp_run.py` | 크롬 단일탭 저수준 조종 + 검색결과 순회·채점 러너 |
| ↳ `portal_worker.py` | 크롬 엔드포인트 탐색·프로필 락·**사장님 유휴 증명**·검색 생존감시 |
| ↳ `portal_live_check.py` (이 디렉터리 최대 파일) | 라이브 준비 진단 + 자격증명·웹훅 초기화 + Supabase 증명 + 라이브 검색 실행 종합 CLI |
| ↳ `match.py` `embed.py` | 저수지 모델 — 프로필 임베딩 적재(pgvector) + 코사인 top-K 후 재랭킹 |
| ↳ `matching_score_contract.py` | LLM 채점 출력 검증 + 점수 계산의 **유일한** 레이어 |
| ↳ `auto_send.py` `inmail_precheck.py` | 발송 게이트 + 원장 (규칙 C의 구현체) |
| ↳ `jd_outreach.py` | InMail 본문 조립 + 글자수 캡 가드 (발송 판단 아님) |
| ↳ `dedup.py` | **수집·색인 단계**의 프로필 URL 정규화·중복 판정. 발송과 무관 — `auto_send.py`는 이 파일을 import하지 않는다 |
| ↳ `grouping.py` | **채용 포지션(JD)** 을 직군·연차로 묶기. 후보 묶기 아님 |
| ↳ `fleet_worker.py` `fleet_dispatch.py` `job_queue.py` | 3대 머신 함대 워커·명령 디스패처·Supabase 작업 큐 |
| Discord 진입점 | 세 곳에 흩어져 있다: `tools/multi_position_sourcing/discord_routing.py`(인가·라우팅), `scripts/discord_direct_gateway.py`(직결 게이트웨이), `apps/aisearch/core/discord_notify.py`(알림) |
| `tests/` | pytest 검사 전부. 파일명 통일 규칙은 없다 |
| `docs/sot/` | 기계 명세(정본). 코드와 충돌하면 **SOT가 이긴다** |
| `docs/engineering/*-goal-*.md` | 작업별 goal 문서 + 적대 검증 로그 |
| `.claude/hooks/` | 자동 가드. `guards/<skill>.py` 한 파일 추가로 새 강제 등록 |
| `.harness/red-ledger.tsv` | 미해결 RED 원장 |
| `skills/` `~/.claude/skills/` | 작업 절차 스킬 |

---

## 6. 이 저장소의 함정 (모르면 반드시 물린다)

- **검사 환경에 numpy·과학계산 라이브러리가 없다.** 설치되는 건 `pytest`, `psycopg`, `playwright`, `discord.py`뿐(`requirements-dev.txt`). 임베딩·코사인 유사도는 **순수 파이썬**으로 쓴다(`embed.py`는 `math`만 씀).
- **CI에는 postgres 16이 붙는다** (`TEST_DATABASE_URL`). 임베딩을 pgvector에 적재하기 때문. 로컬에 DB가 없으면 일부 테스트 동작이 다를 수 있다.
- **`./verify.sh`는 인터프리터를 자동 탐색한다** (`.venv-playwright` → `.venv` → `python3`). 직접 `pytest`를 부르지 말고 항상 `./verify.sh`.
- **스킬·문서도 검사 대상이다.** 새 스킬을 만들면 그 스킬의 계약 테스트를, 근거를 인용하는 문서를 만들면 참조-존재 테스트를 **같은 커밋에** 넣는다. 게이트를 늘리지 않고 `verify.sh` 안에 얹는다. (`test_login_skill_contract.py`, `test_skill_reference_integrity.py` 참조)
- **새 캡처 사이트를 추가하면** 그 사이트의 검사 단언 + 픽스처를 같은 커밋에 넣는다.
- **Stop 훅은 `make task`로 시작한 작업에서만 발동한다.** `scripts/harness/task.sh`가 `.claude/strict-active.json` 마커를 만들고(24시간 유효), 그 마커가 있을 때만 두 가지를 **한 턴** 저지한다 — ① 미커밋 변경을 남긴 종료, ② **"~할까요?"로 되묻고 끝내기**(SOT30 §4.5 R2 질문 금지). 되물어도 되는 건 2FA·캡차·본인확인·파괴적/비가역 작업뿐이다. 즉 **작업 중엔 묻지 말고 끝까지 한다.**
  - 마커 없이 작업하면 아무도 안 막아준다 — 스스로 지킨다. 훅에 막히면 우회하지 말고 원인을 처리한다.
  - 완료의 의미(테스트·배선·증거)는 훅이 판정하지 않는다. 그건 내가 깨고 Codex가 또 깨는 몫이다.
- **LLM 호출은 `claude -p`** (기본 모델 haiku). 호출부 3곳: `llm_keywords.py:341`, `matching_score_contract.py:389`, `fleet_worker.py:1038`. **세 곳 모두 `ANTHROPIC_API_KEY`를 제거한 환경으로 부른다** — 키를 남기면 그 머신에서 조용히 유료 과금으로 흐른다(fail-closed 위반).
- **⚠️ LLM에 "추출"을 시킬 때는 저장소 밖 빈 디렉터리에서, 시스템 프롬프트를 대체해 부른다.** 그냥 부르면 프로젝트·전역 CLAUDE.md와 스킬이 통째로 실려서, 모델이 추출 요청을 작업 지시로 읽고 되묻는다 → JSON이 안 나와 **후보가 통째로 버려진다**. 2026-08-01 실제 라이브 장애. 대응 코드: `matching_score_contract.py:379-395`.
- **워크트리 경로는 `../Valuehire_v5-<slug>`** (`scripts/harness/task.sh:10`). 전역 지침에 적힌 `worktrees/<NAME>/`은 이 저장소에 해당하지 않는다.
- **커밋 메시지는 한국어 권장**, 결과 중심 (`fix(matching): 요건을 더 길게 쓴 게이트도 같은 요건으로 본다`).

---

## 7. 언제 무엇을 읽나 (참조 표)

| 상황 | 읽을 것 |
|---|---|
| 로그인·세션이 얽힘 | `docs/sot/26-portal-login-spec.json` |
| 3대 머신·Discord 명령·계정 바인딩 | `docs/sot/29-fleet-control.md` (+`.json`) |
| 자동 발송 판단 | `docs/sot/28-auto-send-policy.json` |
| 후보 검색 필터·DOM 셀렉터 | `docs/sot/22-*`, `docs/sot/23-channel-dom-selectors.md` |
| 사람이 개입해 브라우징 | `docs/sot/27-humansearch-browsing-preflight.json` |
| Hermes 폐기 작업 | `docs/sot/33-hermes-retirement.md` (HR-0~7 합치지 말 것) |
| 전체 코드 재검토 | `docs/prompts/goal-full-codebase-review.md` |
| 사장님께 최종 보고 | `AGENTS.md` 5칸 형식 |

---

## 8. 작업 방식 기본값

- **직접 한다.** 코드 변경·조사·검증은 이 세션에서 직접 수행한다. 서브에이전트는 사장님이 요청했을 때, 또는 Codex Rescue 독립 검증(게이트 4b)일 때만 쓴다.
  > 전역 지침(`~/.claude/CLAUDE.md:50`)은 "코드를 직접 고치지 말고 executor에 위임하라"고 한다. 같은 파일 최상단(2~8행)이 "충돌 시 절차에 한해 Harness 우선"이라 선언해 두어 **모순은 아니지만**, 위임이 '절차'인지 문언이 애매해 매번 해석이 필요하다. 이 저장소에서는 **위 문장으로 확정**한다.
- **찾기 전에 단정하지 않는다.** "환경이 없다 / 안 된다"고 보고하기 전에 실행 스크립트 → env 로딩 → launchctl → 로그인 셸 → git 이력 → SOT 순서로 전수조사한다.
- **2회 막히면 멈춘다.** 같은 방식으로 두 번 막히면 재시도하지 말고, 무엇이 막혔는지·무엇을 시도했는지 적고 접근을 바꾸거나 사장님께 여쭙는다.
- **범위를 정직히 밝힌다.** 전수조사·감사는 훑은 범위를 먼저 명시하고, 빠진 영역은 "범위 밖"이라 적는다.
