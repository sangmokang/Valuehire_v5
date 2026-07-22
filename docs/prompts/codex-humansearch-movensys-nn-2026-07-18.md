# Codex 실행 프롬프트 — 모벤시스 Physical AI N:N humansearch (LinkedIn RPS + 사람인)

> 이 파일 전체를 Codex에 붙여넣고 `$st` + humansearch 스킬로 실행. 레포: /Volumes/SSD/valuehire_v5.

## 0. 한 줄 목표
모벤시스 Physical AI **포지션 2개**를, 사장님이 걸어둔 **LinkedIn RPS + 사람인** 검색 리스트로
**N:N 순회·채점·등록**한다. 발송은 절대 자동 클릭 금지(사람 게이트).

## 1. 먼저 읽을 SOT·계약 (이 순서, 복제 말고 그대로 따를 것)
- `skills/login/browser-control-contract.json` ← **최우선 안전계약**(브라우저·탭·세션). 어기면 중단.
- `skills/login/SKILL.md` (상태기계 DISCOVER→AI_ATTACHED→HUMAN_AUTH→AUTHENTICATED…)
- `skills/humansearch/SKILL.md` + `skills/humansearch/humansearch.config.json` (순회·채점·등록 정본)
- `docs/sot/26-portal-login-spec.json`(로그인 마커·차단신호), `docs/sot/22`(필터), `docs/sot/23`(DOM)
- `docs/engineering/humansearch-movensys-nn-goal-2026-07-18.md` (이 작업 goal)
- `docs/prompts/linkedin-rps-login-session-fix-2026-07-18.md` (**로그인 문제 원인·해결 정본**)

## 2. 입력 (확정)
**포지션 2개** (ClickUp FY26AI_Search, list `901818680208`):
- `86eyavqwr` = [모벤시스] 국책과제 연구원 (VLA·VLM·Isaac, Physical AI). id `movensys-national-rnd-researcher`.
- `86eyarmu9` = [모벤시스] Physical AI 제어 SW 개발자 (전문연구요원). 축: ROS2·Robot·Robotics·Physical AI·C++·Control·Isaac·Sim-to-Real.

**검색 리스트 (사장님이 이미 걸어둠 — 검색어 재입력·필터 재생성 금지, humansearch 범위)**:
- LinkedIn RPS: 프로젝트 "모벤시스, 국책과제 연구원", 키워드 `VLA OR VLM OR Isaac`, Locations=South Korea, Open-to-work 603명.
  recruiterSearch URL(예; searchRequestId은 매번 갱신되니 라이브 프로젝트에서 연다):
  `https://www.linkedin.com/talent/hire/1766121740/discover/recruiterSearch?searchContextId=187fd876-c2b0-44ef-8a79-5746b34ac2b2&...`
- 사람인: 인재풀 talent-pool, OR=`ros2, issac, isaac, pysical`(오타 포함 사장님 입력 그대로) · AND=`ai`, 경력 3~11년, **4년제 이상만**(전문대·2/3년제 제외), 139명.
- ⛔ 회사명(모벤시스/Movensys)은 검색 키워드에 넣지 않는다.

## 3. ⚠️ 반드시 알아야 할 로그인·세션 문제 (이것 때문에 앞선 시도가 다 막혔다)
1. **LinkedIn Recruiter = 좌석 1개 = 탭 1개.** 자동화가 새 탭/새 세션을 만들면 사장님 세션과
   충돌("multiple sign-ins" / login-cap 리다이렉트). → 계약대로 **기존 로그인 탭 1개에만 raw CDP attach**,
   **새 탭·새 창 0개**, 로그인 대기 중 navigate/click 0회.
2. **디버그 크롬 9225(`portal_browsers.sh cdp linkedin`)는 LinkedIn을 Cloudflare가 하드차단**한다
   (자동화 프로필 플래그). 거기선 로그인 불가.
3. **사장님이 로그인한 진짜 LinkedIn은 디버그 포트가 없는 크롬**에 있어 raw CDP로 못 붙는다.
   → **해결(정본)**: 사장님이 그 크롬을 종료 후 **실제 프로필 그대로** 디버그 포트로 재실행:
   `"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --remote-debugging-port=9222 --user-data-dir="$HOME/Library/Application Support/Google/Chrome"`
   그러면 로그인 세션이 9222에 뜨고 Cloudflare도 통과(실프로필). 그 탭 하나에만 attach.
4. **사람인·잡코리아는 이미 9223/9224에 로그인**돼 있고 좌석충돌·Cloudflare 없음 → 지금 바로 순회 가능.
   즉 **사람인부터 돌리고, LinkedIn은 위 3번 재실행 후** 붙는 게 안전.
5. 로그인·캡차·Cloudflare·2FA·multiple-sign-in은 **사람이 그 창에서 직접 처리**(자동 우회 금지, 계약 규칙 7).
   사장님이 키보드 사용 중이면 HUMAN_ACTIVE — OS idle 180초 전엔 브라우저 조작 0회.

## 4. 채점 (사장님 완화 지시 반영)
- 기본 rubric: 학력30·직무50·논리10·안정10, `score_humansearch()`(tools/multi_position_sourcing/humansearch.py).
- **합격선 70→60으로 낮춤**. 그리고 리스트 헤드라인만으론 점수가 낮게 나오니 **프로필을 열어 이력 전문**을
  봐야 정확하다(스펙: 상세진입→스크린샷→텍스트추출→채점).
- **추가**: 기계점수와 별개로 **"내가(LLM) 볼 때 추천할 이유가 되는 후보"를 근거와 함께 리스팅**한다
  (사장님 지시). LinkedIn은 학교 하드컷 없음, 사람인·잡코리아만 학교컷+4년제.
- 하드제외 재적용(프리랜서·단기이직 2회+·전문대). profile_url 무결성(수확 JSON 원본 복붙, 손입력 금지).

## 5. 출력·기록
- **전부 저장**(점수 무관): 스크린샷→visible_text→results.json→`~/.vh-data/ai-search-candidates.db`.
- **ClickUp FY26AI_Search(901818680208)**: 부모 Task=위 2개(있으면 재사용), 후보는 각 부모 아래
  `profile_url` 중복검사 후 60+만 Subtask. **프로필 저장 증거 없으면 등록 금지**. list id 불일치 금지.
- **Discord 보고 = 사장님 DM**: `scripts/dm_report.py "<메시지>"`(owner 814353841088757800). 시작·중간(페이지 단위 1건)·완료. 완료엔 ClickUp 부모 Task URL 포함. 알람폭탄 금지(묶어서).
- **키워드 변형 재검색**: 순회 후 `humansearch_keyword_expand.py`로 한↔영·불린(AND/OR/NOT) 변형,
  JD 미커버 갭 재검색(LLM 큐레이션). 갭 리포트 완료 DM에 포함.

## 6. 하드 룰 (어기면 중단)
- 제안·InMail·메일 **Send 자동 클릭 절대 금지**(SOT3, 사람 게이트).
- **새 창/새 탭 증식 금지, connectOverCDP/page.close/browser.close/portal_browsers stop·restart 금지**(계약 forbidden).
- 보안 챌린지·세션충돌 감지 즉시 사람 인계(retry 금지). 비밀·쿠키·토큰 출력·복사 금지.
- 검색어 생성·필터 입력은 하지 않는다(사장님이 걸어둠). humansearch는 순회·채점·등록만.

## 7. 이미 해둔 것 (이어받아도 됨)
- LinkedIn 1페이지 14명 수확·저장: `/private/tmp/claude-501/-Volumes-SSD-valuehire-v5/scratchpad/movensys_nn_2026-07-18/linkedin_p1.json`, `scored_p1.json`.
- 그중 Physical AI 강매칭(참고): Jihoon Jung(VLA·ROBOTIS), WonJun Moon(KAIST·VLM), SungHo Moon(SLAM·VLM),
  Kyungmin Lim(On-Device VLM·삼성), nagyeong Kim(Robotics), Kunwoo Park(perception·real-time), Eunhee Kim(Human Motion·GIST).
- 아직 미등록(프로필 상세·증거 확보 후 등록 필요). 사람인은 아직 미착수.

## 8. 실행 순서 권장
1) `$st` 게이트0(과거 회수)·goal 확인 → 2) 사이트 점유권 lock → 3) **DISCOVER**(CDP endpoint·기존 탭 조사)
→ 4) **사람인부터**(9223 로그인됨) raw CDP 1개 attach·배지·순회·채점·등록·DM
→ 5) LinkedIn은 §3.3 재실행으로 9222 노출된 뒤 그 탭에 attach해 이어서
→ 6) 키워드 변형 재검색 → 7) 완료 DM(ClickUp URL 포함).
