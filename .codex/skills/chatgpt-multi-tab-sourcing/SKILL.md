---
name: chatgpt-multi-tab-sourcing
description: 사용자가 "이 포지션으로 ChatGPT 멀티탭 소싱 돌려줘" / "JD 자동 소싱" / "chatgpt-sourcing 실행" 등을 말할 때 Phase 3 MVP 자동화 흐름을 한 번에 처리. 디버그 모드 Chrome 띄우기 → 포지션 CSV 등록 → run --auto-sync → show --latest → Supabase batch sync 까지 끝까지 마무리. 사용자 입력 JD 본문을 받아 CSV 1줄로 평탄화·import·실행 자동화. 트리거: "포지션 자동 소싱", "ChatGPT 탭에 한 번에 입력", "이 JD로 후보자 찾아줘", "sourcing 한 번 더".
---

# ChatGPT 멀티탭 소싱 워크플로우 (Phase 3 MVP)

이 Skill은 사용자가 JD(채용공고) 텍스트를 붙여넣으면 `tools/chatgpt-sourcing/` CLI를 통해 ChatGPT 멀티탭 자동 소싱을 처음부터 끝까지 실행하는 절차입니다.

> 상세 명세: `docs/operations/valuehire-for-inhouse/phase3-chatgpt-sourcing-spec-2026-05-16.md`
> 구현 플랜: `docs/operations/valuehire-for-inhouse/phase3-chatgpt-sourcing-plan-2026-05-16.md`
> 소스 코드: `tools/chatgpt-sourcing/src/`

---

## 1. 언제 트리거되는가

아래 표현 중 하나라도 감지되면 이 Skill을 실행합니다.

- "이 포지션으로 ChatGPT 멀티탭 소싱 돌려줘"
- "JD 자동 소싱" / "sourcing 실행" / "chatgpt-sourcing 실행"
- "이 JD로 후보자 찾아줘" / "이 공고로 소싱해줘"
- "포지션 자동 소싱" / "ChatGPT 탭에 한 번에 입력"
- "sourcing 한 번 더" / "소싱 다시 돌려줘"
- "ChatGPT로 후보자 찾기" / "멀티탭 소싱"

---

## 2. 사전 점검 1단계 — CDP 포트 확인

CLI가 Chrome에 붙으려면 디버그 포트 9222가 열려 있어야 합니다.

```bash
curl -s --max-time 2 http://localhost:9222/json/version
```

**포트가 응답하면** → 3단계로 바로 진행합니다.

**포트가 닫혀 있으면 (`ECONNREFUSED` 또는 타임아웃)** → Chrome을 디버그 모드로 띄웁니다.

```bash
cd /Users/kangsangmo/Desktop/Valuehire_v4/tools/chatgpt-sourcing
node dist/cli.js chrome
```

Chrome이 뜨면 사용자에게 확인을 요청합니다.

> "Chrome이 실행되었습니다. chatgpt.com에 로그인되어 있는지 확인해 주세요. 로그인 완료 후 진행 의사를 알려주세요."

---

## 3. 포지션 등록 흐름 — JD 텍스트 → CSV → import

사용자가 JD 본문을 붙여넣으면 아래 순서로 CSV 1줄을 만들어 `sourcing_positions` 테이블에 등록합니다.

### 3-1. 사용자에게 수집할 정보

JD 본문만으로 처리하되, 아래 메타가 없으면 추출을 시도하고 불명확하면 질문합니다.

| 필드 | 추출 방법 |
|---|---|
| `topic` (파일명용 짧은 식별자) | 직무명 영문 소문자 + 회사 약칭, 예: `backend-toss` |
| `title` | JD에서 직무명 추출 |
| `company` | JD에서 회사명 추출 |
| `body` | JD 본문 전체 |

### 3-2. CSV 1줄 생성 (Python heredoc)

```bash
python3 - <<'PYEOF'
import csv, sys, io

topic   = "TOPIC_HERE"
title   = "TITLE_HERE"
company = "COMPANY_HERE"
body    = """JD_BODY_HERE"""

# 평탄화: 줄바꿈→공백, 큰따옴표→작은따옴표
flat_body = body.replace("\n", " ").replace('"', "'").strip()

out = io.StringIO()
w = csv.writer(out)
w.writerow(["title", "company", "body"])
w.writerow([title, company, flat_body])

path = f"/tmp/{topic}-position.csv"
with open(path, "w", encoding="utf-8") as f:
    f.write(out.getvalue())
print(f"CSV 저장됨: {path}")
PYEOF
```

### 3-3. positions import 실행

```bash
cd /Users/kangsangmo/Desktop/Valuehire_v4/tools/chatgpt-sourcing
node dist/cli.js positions import /tmp/TOPIC_HERE-position.csv
```

등록 후 목록을 확인합니다.

```bash
node dist/cli.js positions list
```

---

## 4. 실행 — run

### 단발 실행 (기본)

```bash
cd /Users/kangsangmo/Desktop/Valuehire_v4/tools/chatgpt-sourcing
node dist/cli.js run --limit 1 --concurrency 1 --auto-sync
```

### N건 일괄 실행

사용자가 "N개 포지션 돌려줘"라고 지정한 경우 `--limit N`으로 조정합니다.

```bash
node dist/cli.js run --limit N --concurrency 3 --auto-sync
```

### 특정 포지션만 지정

`positions list`에서 확인한 `<id>`로 지정합니다.

```bash
node dist/cli.js run --position-id <id> --auto-sync
```

`--auto-sync` 플래그가 붙으면 run 종료 직후 자동으로 Supabase에 결과를 푸시합니다.

---

## 5. 결과 확인 — show --latest

run이 끝나면 점수 내림차순(Desc) 표를 출력하고 사용자에게 보여줍니다.

```bash
cd /Users/kangsangmo/Desktop/Valuehire_v4/tools/chatgpt-sourcing
node dist/cli.js show --latest
```

특정 run을 보려면:

```bash
node dist/cli.js show --run-id <run-uuid>
```

표 항목: `Score | Channel | Type | Candidate | Value | Match | Mismatch`

---

## 6. 에러 처리 — 자주 보는 에러 2가지

| 에러 메시지 | 원인 | 처방 |
|---|---|---|
| `ECONNREFUSED ::1:9222` 또는 `ECONNREFUSED 127.0.0.1:9222` | Chrome 디버그 포트가 닫혀 있음 | `node dist/cli.js chrome` 으로 디버그 모드 Chrome 재실행 후 chatgpt.com 로그인 확인 |
| `modal-no-auth-login` 또는 로그인 오버레이 감지 | chatgpt.com 세션 만료 | Chrome에서 chatgpt.com 직접 로그인 후 CLI 재실행 |

---

## 7. 자동 sync 모드

### --auto-sync (run 옵션, 권장)

```bash
node dist/cli.js run --limit 5 --auto-sync
```

run이 끝나는 즉시 가장 최근 결과를 Supabase에 자동 푸시합니다.

### sync watch daemon (상시 감시)

30초마다 미동기 묶음을 자동으로 Supabase에 올리는 데몬 모드입니다.

```bash
node dist/cli.js sync watch --interval 30000
```

터미널을 닫으면 데몬도 종료됩니다. 백그라운드 유지가 필요하면 `nohup ... &` 또는 별도 터미널 세션에서 실행합니다.

### 수동 배치 sync

```bash
node dist/cli.js sync push --latest           # 가장 최근 run
node dist/cli.js sync push --run-id <uuid>    # 특정 run
```

---

## 8. 재사용 시 주의사항

| 항목 | 값 / 설명 |
|---|---|
| Chrome 프로필 경로 | `~/.cache/valuehire-chatgpt-chrome` (별도 프로필) 또는 기본 Chrome 프로필 (`~/Library/Application Support/Google/Chrome`) — `chrome.ts` 설정에 따름 |
| .env 의존 | `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `ARCHIVE_DB_PATH`, `CDP_ENDPOINT` — `tools/chatgpt-sourcing/.env` 에 반드시 채워야 함 |
| archive.db 경로 | `tools/profile-archiver/server/data/archive.db` — 프로필 아카이버와 파일 공유. 이 경로가 없으면 `ARCHIVE_DB_PATH` 환경변수로 오버라이드 |
| 빌드 필요 여부 | 소스 변경 후에는 `pnpm build` 재실행 필요. `dist/cli.js` 가 없으면 `cd tools/chatgpt-sourcing && pnpm build` |
| 동시 탭 수 기본값 | `--concurrency 3` (spec 기준 최대 10, MVP는 3) |
| 응답 타임아웃 | 탭당 90초. 초과 시 1회 재시도 후 `failed` 마킹 |

---

## 9. 이전 결정·이력 참조

주요 아키텍처 결정 6건(CDP 사용, 로컬 archive.db 우선, Supabase 미러 분리, 채널별 정책 등)과 아키텍처 피벗 내역, 실측 스키마 정정 내용은 아래 메모리 파일에 보존되어 있습니다.

- 메모리 키: `project_chatgpt_sourcing_agent_2026_05_16.md`
- 해당 파일에 의사결정 6건 + `1-pre.2` 아키텍처 피벗 (입력 소스: Supabase → 로컬 archive.db `sourcing_positions`) + `1-pre` 실측 스키마 (`workspace_id`→`owner_email`, `description`→`raw_payload.description`, `status`→`lifecycle_status`) 모두 기록됨.
- 구현 상세는 spec 문서 `1-pre.` 및 `1-pre.2.` 절을 우선 참조합니다.

---

## 호출 예시

사용자: "이 JD로 ChatGPT 멀티탭 소싱 돌려줘" + JD 본문 붙여넣기

1. CDP 포트 `curl` 확인 → 닫혀 있으면 `node dist/cli.js chrome` 실행 + 로그인 확인 요청.
2. JD 본문에서 회사명·직무명 추출 → Python으로 `/tmp/<topic>-position.csv` 생성.
3. `node dist/cli.js positions import /tmp/<topic>-position.csv`.
4. `node dist/cli.js run --limit 1 --concurrency 1 --auto-sync`.
5. `node dist/cli.js show --latest` → 점수 표 사용자에게 보고.
