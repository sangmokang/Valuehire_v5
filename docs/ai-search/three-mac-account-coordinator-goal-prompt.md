# Goal Prompt — AI Search 맥 3대 안전 운영(중앙 계정 코디네이터)

작성일: 2026-06-16 · 대상: harness 게이트로 실행하는 코딩 에이전트
근거 브리핑: `docs/ai-search/ai-search-3mac-strategy-2026-06-16.html`
검증: 코드 직접 인용 + Codex 2차 적대검증(세션 019ed04f)

---

## 0. 이 프롬프트의 목적 (한 줄)

맥북·맥미니·맥에어 **3대로 AI Search를 돌리되, 같은 보호 계정(사람인·잡코리아·링크드인 RPS)을
두 대가 동시에 만지지 못하도록** "중앙 계정 코디네이터"를 만든다. 속도가 아니라 **안 끊김(이중화) + 계정 안전**이 목표다.

> ⚠️ 이 프롬프트 전체는 `docs/harness.md` 게이트(과거 회수 → 인수기준 1개 → RED 먼저 →
> 작은 단위 → ./verify.sh → 2패스 적대검증 → ship)를 **단계마다** 따른다.
> 한 슬라이스 = 한 worktree = 인수 기준 1개. 큰 덩어리 금지(파일 1~5, diff 50~300줄).

---

## 1. 불변식 (절대 약화 금지 — SOT)

1. **3사 자동 로그인을 막지 않는다.** (단, 보안문자/2FA/checkpoint는 자동 우회 금지 — 사람에게 넘김)
2. **사장님이 그 맥에서 크롬을 쓰면 그 맥의 자동작업은 즉시 멈춘다(R4).**
3. **제안·메일·InMail "보내기"는 자동으로 누르지 않는다 — 항상 사람이 마지막에.**
4. **보고는 쉬운 한국어로.** (사장님은 코드 전문가가 아니다)
5. **내 코드를 믿지 않는다 — 작게 만들고, 내가 깨고, Codex가 또 깬다.**

추가 운영 불변식:
- **보호 계정은 한 번에 한 대.** 사람인·잡코리아·linkedin_rps 각각 활성 기기 1대.
- **service-role 키·포털 비밀번호는 허브(Mac mini)에만.** 노트북엔 두지 않는다.
- **admin.valuehire.cc로 이력서 원문·OCR 본문·연락처 원본을 푸시하지 않는다.** 요약·점수·근거 URL·공개 프로필 링크까지만.

---

## 2. 시작 전 — 과거 지시 회수 (게이트 0.5, 건너뛰기 금지)

새로 만들기 전에 이미 있는지 3축으로 grep한다. 있으면 재사용·확장하고, 새로 만들지 않는다.

```bash
# 코드
rg -n "lease|heartbeat|fencing|advisory|locked_by|coordinator|quota|ledger" tools/
rg -n "validated_session_snapshots|VHSS1|session_state_v2" tools/ docs/
# 문서/스킬/메모리
rg -n "코디네이터|분산 잠금|중앙 한도|단일 발신자" docs/ skills/
ls ~/.claude/projects/-Users-kangsangmo-Desktop-Valuehire-v5/memory/
```

확인된 기존 자산(재사용 대상):
- `tools/multi_position_sourcing/portal_worker.py` — 로컬 flock(한 컴퓨터 안 직렬화). **여기에 분산 리스를 얹는다.**
- `tools/multi_position_sourcing/portal_snapshot.py` — VHSS1 암호 스냅샷. **쓰기 가드를 추가한다.**
- `docs/ai-search/session-state-supabase-schema-2026-06-09.sql` — 스냅샷 스키마. **리스/소유권 칼럼을 더한다.**
- `tools/multi_position_sourcing/queue_runner.py`, `portal_runtime.py`, `portal_ops.py` — 한도·채널 정지 로직.

---

## 3. 슬라이스 (위험 큰 것부터, 의존 순서대로)

각 슬라이스는 **인수 기준(무엇이 참이면 끝)**과 **RED 아이디어**를 갖는다. 한 번에 하나만.

### Slice 0 — 링크드인 자동로그인 모순 해소 (P0, 차단요인)
- **문제:** `portal_login.py:495`는 RPS 세션 없을 때 자동로그인을 호출하나,
  `portal_autologin.py:25,74`는 linkedin_rps를 거부/예외. 테스트는 mock이라 실증 0.
- **인수 기준(택1, 사장님 결정):**
  - (A) linkedin_rps 실제 로그인 URL·셀렉터를 구현 + **mock 아닌** 회귀 테스트가 입력칸 채움을 증명, **또는**
  - (B) 정책을 "RPS는 기존 세션 확인 + 만료 시 수동 재로그인"으로 명문화하고, 자동로그인 호출 경로를 그에 맞게 정리.
- **RED:** 현재 mock을 벗기면 linkedin_rps 자동로그인이 `login_url_for_channel` 예외로 실패함을 보이는 테스트.
- **게이트:** 이 슬라이스가 끝나기 전엔 **멀티맥 RPS 켜기 금지.**

### Slice 1 — 중앙 펜싱 리스 (P0, 핵심)
- **인수 기준:** Supabase 계정별 잠금 행. **서버시간 기반 compare-and-set**으로 한 계정은 한 번에 한 기기만
  획득. 발급 시 **단조 증가 펜싱 토큰**을 돌려주고, 하트비트가 끊기면 TTL 만료 후 다른 기기가 인수하되
  **인수 시 토큰이 증가**한다. 행동(검색·저장·발송) **직전마다 토큰 재확인**, 불일치/미보유면 즉시 정지(stop-before-action).
- **RED:** 두 "기기"가 동시에 같은 계정 리스를 요청하면 한쪽만 성공. 하트비트 만료 후 인수 시 토큰 증가.
  옛 토큰으로 행동 시도 시 거부.
- **연결:** `portal_worker.py`의 flock 위에 얹어 "로컬 직렬화 + 글로벌 리스" 2중.

### Slice 2 — 중앙 한도 원장 + 채널 분리 (P1)
- **인수 기준:** 일일 호출 한도(예: 사람인 API 500/일, 70% 상한)를 **모든 맥이 공유하는 한 숫자**로 관리.
  3대 합산이 상한을 넘기지 않음. 링크드인 CDP 끊김이 사람인·잡코리아 채널을 멈추지 않음(채널별 준비상태 분리).
- **RED:** 3 러너가 각자 검색하면 합산 카운트가 중앙에서 증가, 상한 초과 시 거부.
  CDP 미연결을 linkedin_rps에만 적용했을 때 saramin/jobkorea는 계속 진행.
- **근거:** `portal_runtime.py:83`, `portal_ops.py:345`, `portal_queue_executor.py:64`, `queue_runner.py:69`.

### Slice 3 — 스냅샷 소유권·키 분리 (P0/P1)
- **인수 기준:** 스냅샷 **쓰기는 그 계정 리스 보유자만**. 저장에 펜싱 토큰·기기ID·캡처시각(단조) 가드 →
  옛 스냅샷이 새 것을 덮지 못함(last-writer-wins 제거). 암호 키는 **중앙 브로커 또는 기기별 봉투암호화**로,
  원시 복호화 키를 노트북끼리 공유하지 않음. service-role 키는 허브에만.
- **RED:** 리스 미보유 기기의 스냅샷 쓰기 거부. 더 오래된 captured_at 스냅샷의 current 덮어쓰기 거부.
- **근거:** `portal_snapshot.py:60,77,165`, `session-state SQL:16,149,189,260`, `docs/search-access.md:12`.

### Slice 4 — 단일 발신자: 디스코드·admin (P2/P1)
- **인수 기준:** 디스코드 브리핑·admin 푸시는 **미니(허브) 한 대만** 발송. "발송 리스" + **시간창 멱등키**로
  같은 시간대 중복 발송 0. admin은 **단방향(미니 write → admin read), RLS·서버키 보호**, 푸시 내용은 요약·점수·근거 URL·공개 링크까지만.
  정기 주기 스케줄러(launchd) 추가. 미니 다운 시에만 에어가 발송권 인수.
- **RED:** 3대가 동시에 같은 시간창 브리핑을 시도하면 1건만 전송. admin 푸시 페이로드에 이력서 원문/OCR/연락처 원본이 없음(스키마 검사).
- **근거:** `discord_briefing.py:12`, `portal_ops.py:306`, `scripts/valuehire-search-loop.sh`, `multi-position 문서:86`.

### Slice 5 — 이력서 아카이버 이식 (P0)
- **인수 기준:** v4 `tools/profile-archiver`를 **단일 서비스(미니만 기록) + 멱등키**로 이식.
  여러 맥이 한 SQLite 파일을 공유하지 않음(중앙 DB 또는 미니 단독 writer). 저장 오류가 나도 **남은 후보를 계속 저장**(현재는 첫 오류 후 버림).
- **RED:** 한 후보 저장이 예외를 던져도 다음 후보가 저장됨. 같은 canonical URL 중복 저장 시 1건만.
- **근거:** `harvest_runner.py:142`, `multi-position 문서:24,163`, `../Valuehire_v4/tools/profile-archiver`.

### Slice 6 — 에어 페일오버 리허설 (검증 슬라이스)
- **인수 기준:** 미니 강제 종료 → 에어가 사람인·잡코리아 리스 인수 → 옛 세션과 충돌(이중 활성) 0.
  split-brain 미발생을 실측 아티팩트로 증명.
- **RED:** 리스 보유자 프로세스 강제 kill 후 하트비트 만료 → 인수 성공 + 옛 토큰 행동 거부.

---

## 4. 단계마다 — 2패스 적대검증 (게이트 4b, 필수)

각 슬라이스 GREEN 후:
- **패스 1 (내가 깬다):** 빈값·경계·동시요청·하트비트 끊김·토큰 재사용·옛 스냅샷·429·secret 노출·R4 충돌·캡차 분기.
- **패스 2 (Codex가 깬다):** `/codex:rescue`로 같은 슬라이스를 독립 적대검증.
  특히 **split-brain·last-writer-wins·한도 우회·키 노출**을 집중 공격하라고 지시.
- 둘 다 못 깨야 통과. 통과 전 "완료" 보고 금지.

---

## 5. 검증 (게이트 4a)

```bash
./verify.sh            # exit 0, 출력 숫자 그대로 보고
python3 -m unittest tests/test_multi_position_sourcing.py -v
```
- CI는 numpy 없는 순수 파이썬 환경. 임베딩/코사인은 순수 파이썬으로.
- 아티팩트는 `artifacts/` 아래. **비밀값(쿠키·service-role·webhook URL·비밀번호)은 절대 출력/커밋 금지.**

---

## 6. 배송 & 보고 (게이트 5)

- `main` 직접 수정 금지. worktree(`task/<NAME>`)에서 작업 → `make ship` → PR → CI 초록 + merge 전까지 "완료" 없음.
- 사장님 보고는 쉬운 한국어로: **무엇을 했는지 / 왜 / 다음에 뭘 할지**만.
  예: "따로 작업방에서 '한 계정 한 대' 자물쇠를 만들고, 두 번 깨서 확인했습니다. 검사 다 통과(○○개). 다음은 한도 합산이에요."

---

## 7. 절대 하지 말 것 (즉시 정지 조건)

- 중앙 리스가 생기기 전에 사람인·잡코리아를 **두 대 동시 가동**.
- 링크드인 RPS를 **두 대/두 브라우저**에서 켜기.
- service-role 키·포털 비밀번호를 **노트북에 저장**.
- admin·디스코드에 이력서 **원문/OCR/연락처 원본** 푸시.
- 보안문자/2FA/checkpoint **자동 우회**.
- "보내기" **자동 클릭**.

---

## 적대 검증 로그 (2026-06-16 · strict 스킬 2패스)

> 이 문서(계획서)의 **코드 인용 사실성 + 계획의 안전성**을 깬 기록. 본문 그대로 보존.
> 패스1 = Claude 직접, 패스2 = Codex 독립, 그 뒤 Claude가 Codex 증거를 재현(이중검증).

### 결론(양 패스 합치)
**VERDICT: NO — 현 상태로 멀티맥 RPS를 켜면 계정이 안전하지 않다.** 차단급 결함 6건 미해소.

### 패스1 (Claude) 직접 확인 — file:line 증거
- **Slice 0 전제 참**: `portal_login.py:495`가 linkedin_rps에 `_auto_login_session` 호출하나, `portal_autologin.py`의 `AUTO_LOGIN_SELECTORS`에 linkedin_rps 항목 없음 + `login_url_for_channel`이 saramin/jobkorea 외 `raise ValueError`. 자동로그인 모순 실재(메모리 `linkedin-rps-autologin-stub-gap`과 일치).
- **Slice 1 전제 참**: SQL 스키마에 lease/fencing/locked_by/owner/device_id/heartbeat 칼럼 전무 → 신규 필요.
- **Slice 3 last-writer-wins 참**: `session-state-...sql:177-193`/`157-174` 두 ON CONFLICT가 `captured_at = excluded.captured_at`를 단조 가드 없이 무조건 덮어씀.
- **중복 회수**: `rg lease|coordinator|fencing tools/` → 코디네이터 부재 확인(기존 자산은 flock·local pacing뿐). 신규 구축 정당.

### 패스2 (Codex 독립) — agentId af037b42d983e30f0
- 원본 판정 본문: `artifacts/codex-3mac-coordinator-verdict.md` (161줄). Codex VERDICT 줄: **"NO safe to enable multi-Mac RPS as-is."**
- Codex 차단급 우선순위: ①자격증명 모순 ②외부계정 배타성 펜싱만으론 미증명 ③한도 비원자성 ④스냅샷 LWW+클라이언트시각 ⑤admin/디스코드 내용가드 부족 ⑥슬라이스 의존 DAG·멱등키 미명세.

### Claude의 Codex 증거 재현(이중검증) — 직접 재실행
- **A(자격증명 모순, 최상위 차단) 확인**: `portal_live_check.py:937-948` `supabase_config_from_env`가 `SUPABASE_SERVICE_ROLE_KEY` 없으면 `raise RuntimeError`. SQL은 `:93-101`에서 public/anon/authenticated revoke·service_role만 grant. → "service-role은 미니에만"인데 노트북이 lease/heartbeat/quota를 쓸 자격 경로가 문서에 없음. **Slice 1 착수 전 해소 필수.**
- **New5(한도 race) 확인**: `portal_queue_executor.py:46-74` `searches_today`는 호출당 로컬 `count`로 증가(원자적 중앙 예약 없음). 3대 동시 검색 시 합산 상한 우회 가능 → Slice 2 인수기준에 "DB 원자적 reserve/increment" 명시 필요.
- **캡차 분기 확인**: `portal_autologin.py:156-160`가 보안문자/2FA/checkpoint 감지 시 `return False`(자격증명 미제출). 캡차는 코드상 이미 방어됨 → 잔여는 "캡차로 멈춘 동안 보유 리스 처리" 계획 공백뿐.

### Codex가 정정한 내 1차 과장 (정직 공개, strict 5.3)
| # | 내 1차 주장 | Codex 판정 | 정정 |
|---|---|---|---|
| B | "펜싱 토큰은 DB 쓰기만 보호한다" | OVERSTATED | Slice 1은 search/save/send 직전 stop-before-action도 요구함. 다만 **takeover grace > heartbeat 간격·옛 보유자 self-fence·R4 리스 해제**가 인수기준에 없어 외부계정 배타성은 여전히 미보장(결함 자체는 유효). |
| E | "Slice 5 '이식'은 중복" | OVERSTATED | 문서가 `harvest_runner.py`를 직접 가리키고 신규 작업을 좁게(단일writer·멱등·continue) 규정 → 강제 중복 아님. 단 기존 `save_rail` seam 무시 시 중복 위험은 실재. |

### 계획 보강 권고 (착수 전 문서에 반영할 것)
1. **자격증명 모델 명문화**: 코디네이션 테이블 전용 scoped role + RLS(노트북은 service-role 없이 lease/heartbeat/quota만 쓰기). Slice 1의 차단 선결.
2. **R4 양보 = 리스 release(또는 즉시 self-fence)** 인수기준 추가 — TTL까지 계정 잠김 방지.
3. **한도 원장 원자성**: 외부 검색 전 단일 DB RPC/트랜잭션으로 reserve-then-act.
4. **스냅샷 captured_at 서버시각 + 단조 가드**(클라이언트 `datetime.now` 의존 제거).
5. **admin 내용 가드**: 필드 allowlist만으론 summary에 원문 욱여넣기 못 막음 → 의미/길이/PII 누출 테스트 추가.
6. **슬라이스 의존 DAG + 멱등키 서버측 생성·범위(channel/event/window)** 명시.
