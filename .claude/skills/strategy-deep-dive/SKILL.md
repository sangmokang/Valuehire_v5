---
name: strategy-deep-dive
description: 사장님이 "사업 계획서 작성", "PRD 작성", "전략 리서치", "deep dive 리서치", "비전 검증해줘" 같은 요청을 하실 때 사용. 비전·아이디어 한 줄로 시작 → Opus 모델로 3 subagent 병렬 (researcher + scientist + architect) → 통합 HTML 사업계획서 + 한국어 README 인덱스 작성 + 양 repo 미러 + 브라우저 열기까지 한 번에. 2026-05-22 B2C Self-Vetting 사업계획서 작성에서 검증된 패턴. 트리거 — "사업 계획서", "PRD 작성", "전략 deep dive", "비전 검증", "글로벌 리서치"
---

# 전략 Deep Dive — 사업 계획서 + PRD 작성 한 턴 워크플로우

> 2026-05-22 첫 검증 — Valuehire B2C Self-Vetting × Twin Engine × Challenge Mode 사업 계획서(57KB HTML + 한국어 README 인덱스) 25분 안에 작성 완료. 글로벌 경쟁사 deep dive + 사업모델 + PRD 1.0 동시.

---

## 0. 절대 규칙 (R0~R5)

| # | 규칙 | 근거 |
|---|------|------|
| R0 | **가장 비싼 모델(Opus) 강제** | 사장님 "가장 비싼 모델로 진행" 명시. subagent spawn 시 `model: opus` 필수 |
| R1 | **3 subagent 병렬 spawn** — researcher + scientist-high + architect | 각자 다른 각도 deep dive → 메인이 통합. 직렬 진행 금지 |
| R2 | **HTML + 한국어 README 동시 작성** | HTML = 사장님 audit 스타일(Pretendard + Tailwind). README = 한국어 존칭 인덱스 |
| R3 | **양 repo 미러** — Valuehire_v4 + Valueconnect-Ops 동시 | LaunchAgent 자동 sync 적용. master 한 곳만 수정해도 양쪽 |
| R4 | **브라우저 자동 open** | 작성 직후 `open <html>` 으로 사장님 즉시 확인 가능 |
| R5 | **사장님 추가 통찰 즉시 반영** | 통찰 한 번 받을 때마다 HTML Edit + 양 repo sync. iterative 보강 |

---

## 1. 트리거 인식

다음 키워드 감지 시 본 SKILL 활성:
- "사업 계획서 작성"
- "PRD 작성"
- "전략 deep dive"
- "비전 검증해줘"
- "글로벌 리서치"
- "이 아이디어 어떻게 생각해?"
- "경쟁사 분석"

---

## 2. 사장님 비전 파악 (Brainstorming)

받은 메시지에서 다음 추출:
- **핵심 문제 의식** (한 문장)
- **사장님이 떠올린 메타포 / 비유** (예: 결혼정보회사, LeetCode)
- **차별화 후보 요소** (3~5개)
- **타겟 시장** (한국 / 글로벌)
- **연관 도메인** (채용·금융·교육·...)

비전이 모호하면 1~2개 질문 후 진행. 충분히 명확하면 즉시 §3 진입.

---

## 3. 3 Subagent 병렬 Spawn (Opus 모델)

### Subagent A — Global Competitor Deep Dive
```yaml
type: oh-my-claudecode:researcher
model: opus
미션:
  - 글로벌 경쟁사 5~8개 deep dive (가치 제안 / 검증 방식 / BM / 강점 / 약점 / 최근 동향)
  - AI 트렌드 + 시장 규모 + 한국 시장 비교
  - 차별화 white space + 함정 식별
  - WebSearch / WebFetch / context7 적극 활용
출력: markdown 1500 words, 표 + 인용 출처
```

### Subagent B — 사업 모델 + 사용자 Flow
```yaml
type: oh-my-claudecode:scientist-high
model: opus
미션:
  - 양면 시장 역학 (chicken-and-egg 해결책)
  - 사용자 flow N단계 설계 (스테이지별 시간·검증·cheating 방지)
  - 평가 알고리즘 (변별력 차원 + LLM follow-up 패턴)
  - 비즈니스 모델 옵션 분석 (단계별 진화)
  - Cold start 전략 (한국 시장 특수성 활용)
  - KPI + 핵심 의사결정 3가지
출력: markdown 1200 words
```

### Subagent C — PRD 1.0
```yaml
type: oh-my-claudecode:architect
model: opus
미션:
  - Executive Summary + Problem Statement
  - SMART Goals (MVP / 6개월 / 1년 / 3년)
  - Personas 4개 + Top 8 User Stories
  - Core Features F1~F8 (acceptance criteria + edge case)
  - AI 모듈 상세 (LLM 선택 / cheating 방지 / 점수화 rubric)
  - 데이터 모델 (Supabase SQL)
  - 기술 스택 + 마일스톤 M1~M4
  - 리스크 + Open Questions 5개
출력: markdown 1500 words
```

**병렬 spawn**: 3개 Agent tool 호출을 한 메시지에 multiple_tool_use_block 으로. background mode 권장.

---

## 4. 통합 HTML 작성 (사장님 audit 스타일)

### 4-A. 파일 위치
```
~/Desktop/Valuehire_v4/docs/strategy/{도메인}/{프로젝트}-business-plan-{YYYY-MM-DD}.html
```
예시:
- `docs/strategy/b2c/self-vetting-business-plan-2026-05-22.html`
- `docs/strategy/b2b/...`
- `docs/strategy/gtm/...`

### 4-B. HTML 구조 (필수 섹션)

```
1. 헤더 (그라데이션 + 4개 stat 카드)
2. TL;DR (한 문단 결론)
3. 시장 분석 (글로벌 + 한국 + 시장 규모 표)
4. 글로벌 경쟁사 매트릭스 (8개+ 비교 표)
5. 한국 시장 vetting layer 분석
6. Valuehire 차별화 N각 (Pentagon/Hexagon)
7. 함정 3가지 + 완화책
8. 비즈니스 모델 (단계별 진화)
9. 사용자 flow N단계
10. (도메인 특화) 변별력·평가·게이미피케이션 등
11. PRD 1.0 (Personas + User Stories + F1~Fn + AI 모듈 + 데이터 모델 + 기술 스택)
12. 마일스톤 M1~M4
13. KPI / Star Metric
14. 사장님 결정 Q1~Qn (추천안 포함)
15. 부록 — 출처
```

### 4-C. 스타일 표준 (사장님 audit 동일)

```html
<link href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable.min.css">
<script src="https://cdn.tailwindcss.com"></script>
```

색상:
- 헤더: `bg-gradient-to-r from-slate-900 via-slate-800 to-indigo-900`
- 라이트 카드: `bg-white + border-slate-200`
- 강조 카드: `border-l-4 border-{color}-500`
- 신호등: `dot-green / dot-yellow / dot-red`
- 하이라이트: `background: linear-gradient(transparent 60%, #fef3c7 60%)`

폰트: `font-family: "Pretendard Variable"` 한국어 가독성 최강.

---

## 5. 한국어 README 인덱스 작성

위치: `{프로젝트 폴더}/README.md`

구조:
```markdown
# {제목} — Valuehire 차세대 ({도메인})

> 사장님 명시 — {배경 한 줄}.

## 📖 문서 인덱스
| 문서 | 형식 | 설명 |

## 🎯 한 문단 결론

## 💡 핵심 비전 N축

## 🏆 시장 분석 한눈에

## 📊 N년 목표

## 🎯 사장님 결정 필요 — Qn개 질문

## 🛡 핵심 함정 3가지

## 📁 관련 자산 (영구)

## 🔮 다음 단계

## 변경 이력
```

언어: **한국어 존칭 + 비유 우선 + 표 적극 + 짧고 명확.**

---

## 6. 폴더 정리 (사장님 명시 도메인별)

```
docs/strategy/
  README.md                              ← 전체 전략 폴더 인덱스
  b2c/                                   ← B2C 전략 (사장님 첫 도메인)
    README.md
    {프로젝트}-{YYYY-MM-DD}.html
  b2b/ (future)
  gtm/ (future)
```

`docs/strategy/README.md` 신설 — 도메인 매트릭스.

---

## 7. 양 repo 미러 + 브라우저 open

```bash
# 미러 cp
cp ~/Desktop/Valuehire_v4/docs/strategy/{도메인}/{파일}.html \
   ~/Desktop/Valueconnect-Ops/strategy/{도메인}/{파일}.html

cp ~/Desktop/Valuehire_v4/docs/strategy/{도메인}/README.md \
   ~/Desktop/Valueconnect-Ops/strategy/{도메인}/README.md

# 브라우저 open
open ~/Desktop/Valuehire_v4/docs/strategy/{도메인}/{파일}.html
```

**자동 sync 인프라**: LaunchAgent `com.valueconnect.skills-sync` 가 1분 안에 양 repo sync. 다만 strategy/ 폴더는 현재 sync 범위 밖이라 수동 cp.

---

## 8. 사장님 추가 통찰 iterative 반영 (R5)

사장님이 처음 비전 + α 추가 통찰 주시면:
1. 즉시 HTML Edit 으로 새 섹션 추가 (§A, §B, §C 같은 표기)
2. 차별화 N각 N+1각으로 확장
3. 새 KPI / 새 Q 추가
4. README 동기 업데이트
5. `cp + open` 으로 브라우저 리로드

**iterative 패턴이 작동한 사례** (2026-05-22):
- 1차: AI Self-Vetting 검증 모듈 (3 subagent 통합)
- 2차 (사장님): "출제위원 + 평가위원 모델" → §A Twin Engine 신설 + 차별화 5각→6각
- 3차 (사장님): "톱티어 회사 면접 챌린지" → §B Challenge Mode 신설

---

## 9. 응답 형식 (사장님께)

매 단계마다 다음 보고:
1. "**3 subagent (Opus) 병렬 spawn 완료**" — 진행 알림
2. 각 subagent 결과 도착 시 핵심 통찰 한 줄
3. HTML 작성 완료 시 "**브라우저에서 열렸습니다**" + 핵심 섹션 요약
4. README 작성 완료 시 폴더 구조 보고
5. 사장님 결정 필요 Q1~Qn 표

---

## 10. 검증된 산출물 예시 (2026-05-22)

| 항목 | 크기 | 위치 |
|------|------|------|
| HTML 사업계획서 | 57KB | `docs/strategy/b2c/self-vetting-business-plan-2026-05-22.html` |
| README 한국어 | 4KB | `docs/strategy/b2c/README.md` |
| 전략 인덱스 | 1KB | `docs/strategy/README.md` |
| 양 repo 미러 | 동일 | `Valueconnect-Ops/strategy/b2c/` |

소요 시간: 25분 (3 subagent 병렬 약 10분 + HTML 작성 약 10분 + iterative 보강 약 5분)

LLM 비용: Opus 3개 subagent + 메인 HTML 작성 ≈ $3~5

---

## 변경 이력

- **2026-05-22** — 초안. Valuehire B2C Self-Vetting × Twin Engine × Challenge Mode 사업계획서 작성 패턴 영구 자산화. 양 repo 동시 미러 + iterative 보강 패턴 검증.
