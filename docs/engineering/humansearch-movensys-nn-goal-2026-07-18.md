# Goal — humansearch N:N (모벤시스 Physical AI 2포지션 × LinkedIn RPS)

- 트리거: 사장님 /humansearch /goal /strict, 2026-07-18. LinkedIn recruiterSearch URL 1개 + ClickUp 포지션 2개.
- 모드: mixed(라이브 브라우저 순회 = 무코드 실행 + 채점/등록은 기존 코드 재사용) / 위험등급: **L3** (라이브 채용사이트 + ClickUp 등록 + Discord 발송)

## 현재 상태 (직접 확인)
- 포지션1 `86eyavqwr`: [모벤시스] 국책과제 연구원 (VLA·VLM·Isaac, Physical AI) — LinkedIn RPS. 원 id movensys-national-rnd-researcher.
- 포지션2 `86eyarmu9`: [모벤시스] Physical AI 제어 SW 개발자 (전문연구요원). 검색축 한국/ROS2·Robot·Robotics·Physical AI·C++·Control·Isaac·Sim-to-Real.
- 검색 URL: LinkedIn Recruiter recruiterSearch (searchContextId=187fd876…), 사장님이 이미 걸어둠.
- 브라우저: CDP :9222=사람인(기업인증 체크포인트), :9223/:9224=잡코리아, :9225(linkedin 지정)=about:blank 2개. **LinkedIn talent 탭 없음 → 로그인 미확인.**

## 계약 (입출력)
- 입력: recruiterSearch URL(수확 대상) + Position×2(채점 기준).
- 순회·수확: `humansearch_cdp_run.py` 드라이버(모듈 전역 오버라이드), raw CDP 단일탭, 가상스크롤 grab.
- 채점: `score_humansearch()` 학력30·직무50·논리10·안정10, 합격 70+. **N:N** = 1수확 프로필을 두 Position raw 재채점(재오픈 없이).
- 등록: ClickUp FY26AI_Search(901818680208) 부모 Task(포지션별) + 후보 Subtask(70+, profile_url 중복검사, 저장증거 필수).
- 보고: 사장님 DM(hermes_v5, `scripts/dm_report.py`) 중간(페이지 단위 1건)+완료 1건. 완료엔 ClickUp URL 포함.
- 저장: 전원(점수 무관) results.json + 후보 DB.

## 인수 기준
- [ ] 프리플라이트 통과(assert_live_or_abort): 로그인·카드>0·캡차 없음. 실패면 STOP 보고(추측 진행 금지).
- [ ] 수확 프로필 전원 저장(스크린샷→텍스트→results.json+DB).
- [ ] 두 포지션 각각 채점, 70+ 후보만 각 부모 Task Subtask 등록(profile_url 무결성·중복검사·저장증거 게이트 통과).
- [ ] Discord DM 중간·완료 보고(알람폭탄 금지, 묶어서).
- [ ] 발송(제안·InMail·메일) 자동 클릭 0(SOT3).

## 게이트/안전 (L3)
- 사장님 크롬 점유 시 양보→자동 재개. 캡차·로그인 리다이렉트·봇차단 감지 즉시 STOP, 재시도 금지.
- profile_url 손입력 금지(수확 JSON 원본 복붙). 등록 전 3중 게이트(영문학교 보정·hard_exclude 재적용·URL 검증).
- 외부 쓰기(ClickUp/Discord)는 스펙 게이트 통과분만. 발송 아님.

## 비범위
- 검색어 최초 생성·필터 입력(=search/multisearch). 이 작업은 사장님이 걸어둔 결과 순회만.
- InMail 발송(Send). 작성창 준비는 사장님 요청 시에만.
- 사람인·잡코리아 채널(이번 입력은 LinkedIn RPS 검색 1개) — 요청 시 병렬 추가.

## 적대 검증 로그
- 프리플라이트/수확/채점/등록 실증은 실행 후 verdict에 기록.
