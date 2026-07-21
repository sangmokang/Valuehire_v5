---
name: clickup-position-talent-matching
description: 클릭업 FY26ClientsPosition active 포지션 N건을 직무 무관 전방위 채널(잡코리아·사람인·링크드인·ChatGPT·GitHub)에서 매일 정기 자동 매칭. ⚠️ 직무로 채널을 가르지 않는다(2026-06-23 사장님 지시 — "잡코리아=IT" 식 매핑 금지). 적합도 85점 이상 후보자에게 R10 자율 발송. P0/P1/P2 우선순위. 사장님 chrome 미점유 시간대(새벽 03~05 KST) Cron 실행. 사장님 chrome 점유 감지 시 즉시 정지(R4). 트리거 — "포지션 매칭 돌려", "매칭 정기실행", "talent matching cron", "이번주 매칭 자동", "clickup 매칭 1턴", "P0 매칭".
---

# ClickUp Position × Talent Matching (정례화 + Cron)

> 2026-05-24 사장님 명시 — "이 매칭 프로세스를 정례화하고 스킬로 담고 향후 Cron으로 정기적으로 돌리도록 하십시오 /goal"
>
> 본 SKILL = 클릭업 FY26ClientsPosition 의 active 포지션 86건(2026-05-23 기준) × 잡코리아/사람인 인재DB 매칭의 정례화. 매일 새벽 자동 1~2건 처리 → 사장님 깨실 때 새 후보자 카드가 칸반에 올라와 있음.

---

## 0. 절대 규칙 (R0~R15 — 잡코리아·사람인 SKILL R-규칙 상속)

| # | 규칙 | 근거 |
|---|------|------|
| R0 | **85점 이상만 자동 발송** | 잡코리아·사람인 SKILL R0 상속 — 차감 + 실 발송 = 되돌릴 수 없음 |
| R1 | **자격증명은 SKILL 평문 금지** | `~/.secrets/{jobkorea,saramin,openclaw}.env` 격리 |
| R2 | **사람 개입 후 30분 inactive 시 PASS — chrome 탭 활성은 사람 개입 신호 아님** | 사장님 운영 패턴 = LinkedIn composer + 사람인 모달 + 잡코리아 이력서 탭 며칠째 열어둠. R2 보수 적용 시 cron 영원히 0건. 신호 = `.omc/cron-widget-state.json.last_human_signal` 30분 이내일 때만 STOP. 사장님이 "내가 할게"·"잠시 멈춰" 명시하면 `bash scripts/update-cron-widget.sh human` 자동 호출되어 timestamp 갱신. 2026-05-25 R34 신설(아래 R34 참조) |
| R3 | **봇 검출(캡차/차단/2FA) 즉시 STOP** | 재시도 금지 — 계정 잠금 위험 |
| R4 | **인재DB 라이선스 차감 사장님 컨펌 후** | 잡코리아 1건 발송 = 1건 차감 / 사람인 동일. 잔여 < 5 시 충전 요청 STOP |
| R5 | **'프리랜서' 단어 포함 레쥬메는 패스** | 잡코리아·사람인 SKILL R5 상속 |
| R6 | **잡코리아 등록 포지션 사전 확인 → 없으면 §13-A 자동 등록 fallback** | jobkorea SKILL R6 상속 |
| R7 | **한국어 키워드 입력 안전 패턴** | clipboard + cmd+v + 검증 |
| R8 | **비IT 도메인도 같은 흐름** | 직무 트리 매핑만 다름 |
| R9 | **막힘·실패 시 무조건 재시도 강제** | jobkorea R9 상속 — 캡차 외 모두 재시도 |
| R10 | **사장님 컨펌 묻지 말고 자율 진행 — 발송 완수가 최우선** | jobkorea/saramin R10 상속. 결과만 Discord 종합 보고 |
| R11 | **Discord 송부 시 후보자 profile URL 필수 — embed.url 누락 = abort + 재송부** | jobkorea R11 상속 |
| R12 | **등록 포지션 직무·JD 일치 검증 + 미리보기 사장님 송부 필수** | jobkorea R12 — 모벤시스 사고 재발 방지 |
| R13 | **자동화 도중 발견한 root cause → QA-XXX 즉시 영구 등록** | jobkorea R31 상속 |
| R14 | **사장님 코칭 즉시 R-번호 부여 → SKILL 영구화** | jobkorea R32 상속 |
| **R15 (본 SKILL 신설)** | **중복 후보자 발송 방지** — 이미 사장님이 LinkedIn/사람인/잡코리아에서 진행 중인 후보자(`pipeline_candidates.metadata.outreach` 또는 ClickUp 후보자 task 존재)는 발송 SKIP | 모벤시스 차민우/권상윤/정대성 같은 사례 재발 방지 |
| **R16 (본 SKILL 신설)** | **하루 최대 처리 = 잡코리아 8건 + 사람인 12건** | 채널별 일일 차감 한도 보호. 잡코리아 300/년 · 사람인 한도 별도 |
| **R17 (본 SKILL 신설)** | **Cron 실행 시간대 = 새벽 03~05 KST 한정** | 사장님 chrome 미점유 시간대. 그 외 시간 트리거 시 즉시 정지 (수동 호출은 예외) |
| **R34 (2026-05-25 신설)** | **chrome 탭 활성 ≠ 사람 활동** — `tabs_context_mcp` 만으로는 STOP 판정 금지 | 사장님 명시(2026-05-25) "탭은 며칠째 열어두는 운영 패턴이라 R2 보수 적용 시 cron 영원히 0건". 진짜 사람 활동 신호는 `last_human_signal` timestamp(.omc/cron-widget-state.json) — 사장님 명시적 "잠시 멈춰" / "내가 할게" 신호 시 갱신. 30분 이내면 STOP, 그 외 PASS. |
| **R35 (2026-05-25 신설)** | **Cron 동작 시 화면 widget으로 시각화** | 사장님 명시(2026-05-25) "작은 시각화 화면에 나타나면서 Cron 동작중 표기". `.omc/cron-widget.html` (chrome 작은 floating window 280x70, 우측 상단 1700,50) → `.omc/cron-widget-state.json` 5초 polling. 4가지 상태: 🟢 running / ⚫ idle / 🛑 paused / ✅ done. cron 진입·종료·정지마다 `bash scripts/update-cron-widget.sh <status> <label> <detail>` 호출. |

---

## 1. 채널 라우팅 규칙 (사장님 2026-05-24 명시)

| 클릭업 status | 채널 | 근거 |
|--------------|------|------|
| `ai/ml/data` | **잡코리아 1순위** | 주니어·테크 지원자 풍부 |
| `backend/fullstack/cto` | **잡코리아 1순위** | 동일 |
| `frontend` | **잡코리아 1순위** | 동일 |
| `app` | **잡코리아 1순위** | 동일 |
| `devops/sre/security/qa` | **잡코리아 1순위** | 동일 |
| `po/pm/기획` (IT) | **잡코리아 1순위** | IT 도메인 한정 |
| `designer` (UX/UI) | **잡코리아 1순위** | IT 디자인 |
| `marketing` | **사람인 1순위** | 비IT 풍부 |
| `sales/bd` | **사람인 1순위** | 비IT 풍부 |
| `hr/finance/strategy/etc` | **사람인 1순위** | 비IT 풍부 |
| `c-level` / `etc` | **사람인 우선** | 케이스별 판단 |

### 채널 라우팅 함수

```typescript
function routeChannel(status: string): 'jobkorea' | 'saramin' {
  const jobkoreaStatuses = [
    'ai/ml/data', 'backend/fullstack/cto', 'frontend', 'app',
    'devops/sre/security/qa', 'po/pm/기획', 'designer'
  ];
  return jobkoreaStatuses.includes(status) ? 'jobkorea' : 'saramin';
}
```

---

## 2. 입력 자산

| 자산 | 위치 | 역할 |
|------|------|------|
| **active 포지션 인벤토리** | `.omc/linkedin-bulk-active.jsonl` | 86건 × 16개 회사 (P0/P1/P2) |
| **P0 키워드 사전** | `.omc/p0-jd-keywords.json` | 5축 분해 + 회사 brief + 진행 이력 |
| **진행 상태** | `.omc/matching-progress.json` | 마지막 처리 시간 + 처리한 clickup_id 목록 + 채널별 일일 카운터 |
| **잡코리아 자격증명** | `~/.secrets/jobkorea.env` | $JOBKOREA_ID/$JOBKOREA_PW |
| **사람인 자격증명** | `~/.secrets/saramin.env` (부재 시 chrome saved password) | `[[reference_saramin_env_missing]]` |
| **사람인 등록 포지션** | 2026-05-23 batch 76건 | commit c2c9e46 |

---

## 3. 메인 흐름 (의사 코드)

```typescript
async function matchingTurn({ mode }: { mode: 'cron' | 'manual' | 'p0-only' }) {
  // (1) 사전 게이트
  await assertChromeIdle();         // R2 — 사장님 chrome 점유 시 즉시 STOP
  await assertCronTimeWindow(mode); // R17 — cron 모드는 03~05 KST 한정

  // (2) 진행 상태 로드
  const progress = readProgress('.omc/matching-progress.json');
  const today = new Date().toISOString().slice(0, 10);
  if (!progress.daily_count[today]) progress.daily_count[today] = { jobkorea: 0, saramin: 0 };

  // (3) 인벤토리 로드 + 처리 안 된 것 + 우선순위 정렬
  const positions = readJsonl('.omc/linkedin-bulk-active.jsonl')
    .filter(p => !progress.processed_clickup_ids.includes(p.clickup_id))
    .sort((a, b) => a.priority.localeCompare(b.priority));  // P0 → P1 → P2

  // (4) 매칭 1턴 (1~2건)
  const maxPerTurn = mode === 'p0-only' ? 9 : 2;
  let processed = 0;

  for (const pos of positions) {
    if (processed >= maxPerTurn) break;

    const channel = routeChannel(pos.status);
    const dailyCount = progress.daily_count[today][channel];

    // R16 — 하루 한도
    if (channel === 'jobkorea' && dailyCount >= 8) {
      log.info(`잡코리아 일일 한도 도달 (8/8) — 사람인으로 폴백 검토 또는 내일 진행`);
      break;
    }
    if (channel === 'saramin' && dailyCount >= 12) {
      log.info(`사람인 일일 한도 도달 (12/12) — 내일 진행`);
      break;
    }

    // (5) JD 본문 + 키워드 분해
    const jd = await clickup_get_task(pos.clickup_id);
    const keywords = extractKeywords(jd, pos);     // §1 매핑

    // (6) 중복 후보자 검증 사전 (R15)
    const linkedinActive = pos.linkedin_active === true;
    const linkedinActiveNote = pos.linkedin_active_note;

    // (7) 채널 SKILL 호출 (자율 모드)
    let result;
    if (channel === 'jobkorea') {
      result = await invokeSkill('jobkorea-talent-sourcing', {
        company: pos.company,
        position: pos.position,
        jd_text: jd.description,
        keywords,
        autonomous: true,                          // R10 — 사장님 컨펌 0
        skip_candidates: linkedinActive ? getLinkedinProgressNames(pos) : [],
      });
    } else {
      result = await invokeSkill('saramin-talent-sourcing', {
        company: pos.company,
        position: pos.position,
        jd_text: jd.description,
        keywords,
        autonomous: true,
        skip_candidates: linkedinActive ? getLinkedinProgressNames(pos) : [],
      });
    }

    // (8) 결과 기록
    progress.processed_clickup_ids.push(pos.clickup_id);
    progress.daily_count[today][channel] += result.sent_count;
    progress.last_run = new Date().toISOString();
    writeProgress(progress);

    // (9) Discord 종합 보고
    await discord.report({
      channel: 'OPS_CANDIDATES',
      title: `📦 매칭 1턴 — ${pos.company} / ${pos.position}`,
      result: result,                              // {reviewed, sent, skipped, top_candidates: [...]}
    });

    processed++;

    // (10) 다음 포지션 sleep (10분 — 사람 패턴 시뮬레이션)
    if (processed < maxPerTurn) await sleep(10 * 60 * 1000);
  }

  // (11) 턴 종료 보고
  await discord.report({
    channel: 'OPS_CANDIDATES',
    title: `✅ 매칭 턴 종료 — ${processed}건 처리`,
    body: `잡코리아 일일: ${progress.daily_count[today].jobkorea}/8\n사람인 일일: ${progress.daily_count[today].saramin}/12\n다음 트리거: 새벽 03:00 KST`,
  });
}
```

---

## 4. 사전 게이트 함수 (R2 + R17)

```typescript
async function assertChromeIdle() {
  // R34 (2026-05-25) — chrome 탭 활성 ≠ 사람 활동. last_human_signal timestamp 기반.
  const state = readJson('.omc/cron-widget-state.json');
  const lastHumanSignal = new Date(state.last_human_signal || 0);
  const minutesAgo = (Date.now() - lastHumanSignal.getTime()) / 60000;

  if (minutesAgo < 30) {
    // R35 — 위젯 paused 상태로 갱신
    sh('bash scripts/update-cron-widget.sh paused "🛑 사람 개입 감지" "30분 후 재시도 (현재 ' + Math.round(minutesAgo) + '분)"');
    throw new HumanInterventionError(
      `사장님 활동 ${Math.round(minutesAgo)}분 전 — 30분 후 재시도. last_human_signal=${state.last_human_signal}`
    );
  }

  // 30분 이상 inactive → PASS (cron 진입 OK)
  return true;
}

// 사장님이 "내가 할게" / "잠시 멈춰" 명시할 때 호출
function markHumanSignal() {
  sh('bash scripts/update-cron-widget.sh human');
}

async function assertCronTimeWindow(mode: string) {
  if (mode === 'manual') return;  // 수동 호출은 항상 통과

  const hour = new Date().getHours();  // KST (local)
  if (hour < 3 || hour > 5) {
    throw new Error(`Cron 시간대 위반 — 현재 ${hour}시. 03~05 KST 한정`);
  }
}
```

---

## 5. 중복 후보자 검증 (R15)

```typescript
async function getLinkedinProgressNames(pos: Position): Promise<string[]> {
  // (a) ClickUp 후보자 task 검색 — 회사명 + 포지션명 매칭
  const candidateTasks = await clickup_search({
    keywords: `${pos.company} ${pos.position}`,
    filters: { task_statuses: ['active', 'unstarted', 'done'] }
  });
  const names = candidateTasks.map(t => extractCandidateName(t.name));

  // (b) Supabase pipeline_candidates 매칭
  const { data } = await supabase
    .from('pipeline_candidates')
    .select('name')
    .eq('client_company', pos.company)
    .ilike('metadata->>outreach->>position', `%${pos.position}%`);
  names.push(...data.map(d => d.name));

  // 중복 제거
  return [...new Set(names)];
}
```

채널 SKILL(jobkorea/saramin)에서 `skip_candidates` 파라미터 받으면 매칭 시 동명이인 1차 SKIP. 동명이인이 아니면(다른 학교/경력) 진행 OK.

---

## 6. Cron 등록

### 6.1 etc/crontab (시스템 cron)

매일 새벽 03:00 KST 트리거:

```bash
# /etc/crontab 또는 사용자 crontab
0 3 * * * /Users/kangsangmo/.claude/scripts/run-matching-turn.sh >> /tmp/clickup-matching.log 2>&1
```

### 6.2 Claude Code 세션 내 Cron (CronCreate)

세션 내 Cron — 7일 자동 만료. 사장님이 Claude Code 켜둔 상태에서만 동작.

```typescript
CronCreate({
  cron: "3 3 * * *",  // 매일 03:03 KST (off-minute, fleet 회피)
  prompt: "clickup-position-talent-matching SKILL을 cron 모드로 실행하라. 사장님 chrome 점유 시 즉시 정지. R10 자율 발송. Discord OPS_CANDIDATES 보고.",
  recurring: true,
  durable: true  // .claude/scheduled_tasks.json 영속화
})
```

### 6.3 wakeup script (`~/.claude/scripts/run-matching-turn.sh`)

```bash
#!/bin/bash
# Claude Code 세션 깨우기 + SKILL 호출 (시스템 cron 용)
# 사장님이 Mac 켜져있고 Claude Code 실행 중이면 동작

osascript -e 'tell application "Claude" to activate'
sleep 5

# Claude Code CLI 호출 (또는 Discord webhook 으로 SKILL 트리거 알림만)
discord-webhook --channel OPS_OPS \
  --title "🤖 매칭 Cron 트리거" \
  --body "새벽 03:00 — clickup-position-talent-matching SKILL 실행 요청. Claude Code에서 트리거 또는 사장님 수동 확인."
```

⚠️ **권장**: 6.2 (Claude Code CronCreate) 1차. 6.3 (시스템 cron + Mac 깨우기) 는 2차 — Mac 꺼져있으면 동작 안 함.

---

## 7. 결과 보고 형식 (Discord OPS_CANDIDATES)

### 7.1 1포지션 매칭 1턴 보고

```
📦 매칭 1턴 — {회사} / {포지션}
채널: {잡코리아|사람인}
검토 후보자: N명 (펼친 카드)
85점 이상 자동 발송: M명
85점 미만 컨펌 대기: K명
패스(프리랜서/저점/중복): P명

🏆 발송 명세:
1. {이름1}OO · 92점 · {매칭근거 1줄} · 칸반 등록 ✅
2. {이름2}OO · 88점 · ...

잔여 채널 차감: 잡코리아 {N}/300 · 사람인 {S}/한도
다음 처리: {다음포지션}
```

### 7.2 턴 종료 종합 보고

```
✅ 매칭 턴 종료 — {processed}건 처리 ({mode})

처리 회사·포지션:
- {회사1} / {포지션1} — 잡코리아 → 2명 발송
- {회사2} / {포지션2} — 사람인 → 3명 발송

오늘 일일 누적: 잡코리아 5/8 · 사람인 7/12
잔여 미처리 active: {N}건 (P0 {p0}, P1 {p1}, P2 {p2})

다음 트리거: 새벽 03:03 KST (Cron)
또는 사장님 수동 "P0 매칭 계속" / "다음 매칭 1턴"
```

---

## 8. 실행 모드 (사장님 명시 트리거)

| 사장님 명령 | 모드 | 동작 |
|----------|------|------|
| "포지션 매칭 1턴 돌려" | `manual` | 사전 게이트 통과 시 1턴 즉시 (최대 2건) |
| "P0 매칭 한 번에" | `p0-only` | P0 9건 모두 시도 (chrome 점유 없을 때 최대 ~90분) |
| "매칭 정기실행 설정" | (config) | CronCreate 등록 + 6.2 영속화 |
| "매칭 일단 정지" | (pause) | progress.paused = true → cron 트리거 시 즉시 종료 |
| "매칭 재개" | (resume) | progress.paused = false |
| (Cron 자동) | `cron` | 03~05 KST 한정. 사장님 chrome 점유 시 STOP. 최대 2건/턴 |

---

## 9. 사람인·잡코리아 SKILL 통합 (R9 cascade)

본 SKILL 은 사람인·잡코리아 SKILL의 **오케스트레이션 레이어**. 실제 매칭/발송은 채널 SKILL이 수행:

```
clickup-position-talent-matching (orchestrator)
   ↓ channel routing
   ├─→ jobkorea-talent-sourcing SKILL (IT/AI/Data)
   │     ↓ §13-A 자동 등록 fallback
   │     ↓ 85점+ 자율 발송
   │     ↓ Discord OPS_CANDIDATES
   │
   └─→ saramin-talent-sourcing SKILL (마케팅/세일즈/HR/재무)
         ↓ 발송
         ↓ Discord OPS_CANDIDATES
```

각 채널 SKILL의 R-규칙은 그대로 적용. 본 SKILL 은 **언제·어떤 포지션·어떤 채널** 만 결정.

---

## 10. 첫 라이브 실행 (사장님 chrome 해제 신호 대기)

### 10.1 사전 조건 (BLOCKING)

다음 모두 충족 시 진입:
1. **사장님 chrome 점유 해제** — LinkedIn composer + 사람인 모달 + 잡코리아 이력서 모두 닫기
2. **사장님 명시 신호** — "P0 매칭 시작" 또는 "매칭 1턴 돌려"
3. **잔여 차감 확인** — 잡코리아 > 50 / 사람인 라이선스 유효

### 10.2 첫 1턴 시나리오 (P0 IT 4건 잡코리아)

1. 매드업 AI Engineer (urgent) — 잡코리아 → 적합도 85+ 자동 발송 (R10)
2. 핵클 백엔드 엔지니어 — 잡코리아 → §13-A 자동 등록 (포지션 미등록 가능성) → 발송
3. 모벤시스 Physical AI Engineer — R15 중복 검증 (차민우/권상윤/정대성 제외) → 발송
4. 뤼튼 [AX CIC] AX Project Manager — 잡코리아 → 발송

각 포지션 1턴 = 약 30~50분. 4건 = 약 2~3시간. 중간 사장님 chrome 개입 시 즉시 정지.

---

## 11. Acceptance Criteria (1차 완료 정의)

다음 모두 참이면 SKILL 1차 완료:

- [ ] 본 SKILL 트리거 키워드 6종 노출
- [ ] 사전 게이트 (R2 + R17) 동작 검증
- [ ] 채널 라우팅 함수 12개 status 모두 매핑
- [ ] 중복 후보자 검증 (R15) — 모벤시스 진행 이력 SKIP 확인
- [ ] 일일 한도 (R16) — 잡코리아 8 / 사람인 12 강제
- [ ] Cron 등록 (6.2 CronCreate) — 매일 03:03 KST 자동 트리거
- [ ] 첫 라이브 1턴 — P0 IT 1건(매드업 AI Engineer 권장) 정상 매칭·발송
- [ ] `.omc/matching-progress.json` 진행 추적 동작
- [ ] Discord OPS_CANDIDATES 종합 보고 동작

---

## 12. 변경 이력

- 2026-05-24 — SKILL 신규 작성. 사장님 명시 "매칭 프로세스 정례화 + SKILL + Cron". 잡코리아 SKILL R0~R32 + 사람인 SKILL 흐름 상속. R15(중복 후보자) / R16(일일 한도) / R17(Cron 시간대) 신설. P0 IT 4건 사전 키워드 분해 완료(`.omc/p0-jd-keywords.json`).

---

## 13. 참고 메모리

- [[project-linkedin-rps-jd-set-builder-2026-05-23]] — JD Set Builder (관련 자산: `.omc/linkedin-bulk-active.jsonl`)
- [[project-saramin-bulk-register-2026-05-23]] — 사람인 76건 등록 batch (commit c2c9e46)
- [[project-jobkorea-sourcing-2026-05-22]] — 잡코리아 R-규칙 누적 패턴
- [[project-saramin-v2-live-validation-2026-05-23]] — 사람인 R9~R13 라이브 학습
- [[feedback-human-intervention-pause]] — 사장님 chrome 활동 시 자동화 정지
- [[reference-saramin-env-missing]] — 사람인 자격증명 부재 → chrome saved password 활용
