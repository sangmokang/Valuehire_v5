---
name: chatgpt-batch-worker
description: 사용자가 "ChatGPT로 N개 한꺼번에 분류해줘" / "ChatGPT 배치 실행" / "ChatGPT 멀티탭 워커로 처리" / "이거 ChatGPT에 자동으로 돌려서 답 가져와" 등을 말할 때 사용. tools/chatgpt-sourcing 의 batch 모드(0원 운영 자동화)를 활용해 임의의 prompt 묶음(회사 분류·B2C 초대 메시지·뉴스 번역·요약 등)을 ChatGPT 멀티탭으로 처리. 입력 JSONL → ChatGPT N탭 동시 처리 → 출력 JSONL. rate limit 자동 백오프, resume, JSON 자동 추출 포함. 트리거: "1000개 한꺼번에", "ChatGPT 자동화로 분류", "배치로 답 받아와", "회사 N개 ChatGPT로 분류", "B2C 초대 메시지 생성".
---

# ChatGPT 멀티탭 배치 워커

이 skill 은 임의의 프롬프트 묶음을 ChatGPT 창에 자동 입력해서 답을 받아오는 **범용 워커**를 호출합니다.
**비용 0원** (사장님의 ChatGPT Plus/Pro 구독만 사용. OpenAI API 결제 X).

> 명세: `docs/operations/chatgpt-multitab-worker-product-spec-2026-05-18.md`
> 소스 코드: `tools/chatgpt-sourcing/src/batch.ts` + `cli.ts`
> 관련 skill: `chatgpt-multi-tab-sourcing` (JD→후보자), `chatgpt-position-sourcing` (/kanban PeekView)

---

## 1. 언제 사용하는가

같은 패턴 — **"입력 1줄 → ChatGPT 한 번 호출 → 결과 JSON 1줄"** — 이 반복되는 모든 작업.

| 사용 사례 | 예 |
|---|---|
| 회사 N개를 분류 체계에 매핑 | 미분류 908개 → 33 클러스터 중 하나 |
| 1촌/리드 대량 맞춤 메시지 생성 | 1000명 B2C 초대 메일 본문 |
| 영문 기사 한국어 번역 + 요약 | 뉴스레터 100건 |
| JD 본문에서 키워드/스킬 추출 | 8000건 JD 정제 |
| 후보자 강점/약점 평가 | (이미 `match` 명령이 있음 — 그쪽 사용) |
| 다국어 변형 생성 | 동일 본문의 영/일/중 번역 |

호출자가 결정하는 것은 **프롬프트 텍스트와 결과 스키마**뿐입니다. 탭 풀, rate limit 대응, 재시도, JSON 추출은 워커가 처리합니다.

---

## 2. 사전 점검 — Chrome 디버그 포트

```bash
curl -s --max-time 2 http://localhost:9222/json/version
```

**닫혀 있으면**:
```bash
cd /Users/kangsangmo/Desktop/Valuehire_v4/tools/chatgpt-sourcing
node dist/cli.js chrome
# 디버그 Chrome 창이 뜨면 chatgpt.com 에 로그인되어 있는지 확인
```

사용자 확인:
> "디버그 Chrome 이 실행되었습니다. chatgpt.com 에 로그인되어 있는지 확인해 주세요."

---

## 3. 입력 JSONL 만들기

입력 파일 각 줄은 다음 형식의 JSON 객체입니다.

```jsonl
{"key": "고유키1", "prompt": "ChatGPT에 보낼 전체 프롬프트", "metadata": {"foo":"bar"}}
{"key": "고유키2", "prompt": "...", "metadata": {...}}
```

- `key` (필수, 문자열): 결과를 다시 매핑할 때 쓰는 고유 ID. UUID 또는 의미 있는 ID 권장.
- `prompt` (필수, 문자열): ChatGPT 에 그대로 입력될 텍스트. 결과 형식을 명시하는 게 좋습니다 (JSON 배열·객체 등).
- `metadata` (선택, 객체): 워커는 건드리지 않고 그대로 결과에 전달. 매핑·디버깅·후처리에 사용.

### 3-1. 권장 프롬프트 패턴

```
당신은 ... 전문가입니다.
아래 ... 를 ... 해주세요.

## 컨텍스트
{사용자 데이터}

## 출력 형식
JSON 배열만 출력하세요. 다른 텍스트나 코드펜스 금지.
[
  {"idx": 1, "key": "값", ...},
  ...
]
```

### 3-2. 한 prompt 에 여러 항목 묶기 (효율적)

ChatGPT 1회 호출에 ~30~60초 걸리므로, 가능하면 한 프롬프트에 10~30개 항목을 묶어 JSON 배열 형태로 받는 게 빠릅니다.
응답은 `--parse-json` 으로 자동 추출되어 `parsed` 필드에 들어갑니다.

---

## 4. 실행

```bash
cd /Users/kangsangmo/Desktop/Valuehire_v4/tools/chatgpt-sourcing
node dist/cli.js batch \
  --input /절대/경로/input.jsonl \
  --output /절대/경로/output.jsonl \
  --concurrency 6 \
  --parse-json \
  --max-retries 3 \
  --resume
```

| 옵션 | 기본 | 설명 |
|---|---|---|
| `--input <path>` | 필수 | 입력 JSONL |
| `--output <path>` | 필수 | 결과 JSONL (append 모드 — 진행 중 보존) |
| `--concurrency <n>` | 1 | 동시 ChatGPT 탭 수. 6 권장. 머신/계정에 따라 조절 |
| `--parse-json` | off | 응답에서 JSON object/array 자동 추출 → `parsed` 필드 |
| `--cooldown-ms <ms>` | 0 | 같은 탭에서 다음 prompt 전 대기. rate limit 회피용 |
| `--max-retries <n>` | 2 | 일반 오류 재시도. rate limit 재시도는 별도(자동) |
| `--resume` | off | 출력 파일에 `ok=true` 인 key 는 skip |
| `--start-url <url>` | `chatgpt.com` | 다른 ChatGPT 프로젝트 컨텍스트 사용 시 |

### 4-1. 백그라운드 실행 + 진행 모니터링

장시간 (수십 분) run 은 백그라운드:
```bash
node dist/cli.js batch ... 2>&1 | tee /tmp/batch.log &
# 진행률 보기
wc -l output.jsonl   # 처리된 라인 수
tail -n 5 /tmp/batch.log
```

---

## 5. 출력 JSONL 해석

각 줄:
```json
{
  "key": "...",
  "ok": true,
  "raw": "ChatGPT 가 돌려준 원본 텍스트",
  "parsed": { /* JSON 자동 추출 결과, 또는 undefined */ },
  "attempts": 1,
  "duration_ms": 35234,
  "ts": "2026-05-18T07:55:12.123Z",
  "metadata": { /* 입력에서 그대로 */ }
}
```

실패 시:
```json
{ "key": "...", "ok": false, "error": "에러 메시지", "attempts": 3, "duration_ms": 90000, "ts": "...", "metadata": {...} }
```

---

## 6. 안전장치 (자동 동작)

| 상황 | 자동 처리 |
|---|---|
| "You've sent too many messages" / "잠시 후 다시" rate limit 메시지 | 60초 → 90초 → 135초 → ... 지수 백오프 후 재시도. 누적 최대 6회 (~30분) |
| Cloudflare / "Verify you are human" 화면 | 즉시 실패 + 호출자에게 알림. 사람 개입 필요 |
| 프롬프트 한도 초과 ("message too long") | 즉시 실패. 프롬프트를 더 잘게 쪼개야 함 |
| send 버튼이 paste 후 활성화 안 됨 | 최대 60초 대기 후 일반 오류 처리 |
| 응답 도중 새 rate limit 출현 | 진행 중인 prompt 폐기 → 재시도 |
| 일시적 "Something went wrong" | 3초 대기 후 새로고침 후 재시도 |

---

## 7. 사용 예제 모음

### 7-1. 회사 N개 33-클러스터 분류

```bash
# 1) 입력 JSONL 생성 (도메인별 스크립트)
python3 scripts/prepare_chatgpt_classify_input.py \
  --input clusters.json --output input.jsonl --batch-size 20

# 2) 배치 실행
node dist/cli.js batch --input input.jsonl --output output.jsonl \
  --parse-json --concurrency 6 --max-retries 3 --resume

# 3) 결과 적용
python3 scripts/apply_chatgpt_classify_output.py
```

### 7-2. B2C 1촌 1000명 맞춤 초대 메시지 (예시)

```jsonl
{"key": "user-001", "prompt": "다음 1촌 정보로 자연스러운 초대 메일 본문을 작성. {name, 직무, 회사, 공통접점}. JSON {\"subject\":..,\"body\":..} 만 출력.", "metadata": {"email":"..."}}
```

→ `--concurrency 6 --cooldown-ms 5000 --resume` 권장 (계정 보호).

### 7-3. 영문 기사 100건 한국어 번역+요약

```jsonl
{"key": "news-2026-05-18-techcrunch-001", "prompt": "다음 영문 기사를 한국어로 번역하고 3문장으로 요약. JSON {\"title\":..,\"summary_ko\":..,\"full_translation\":..}.\n\n원문: ...", "metadata": {"source":"techcrunch","url":"..."}}
```

---

## 8. 새 작업 추가 — 10분 안에

1. 입력 데이터 → JSONL 변환 스크립트 작성 (`scripts/prepare_<topic>_input.py`)
2. 위 4번 명령 실행
3. 결과 JSONL 후처리 스크립트 작성 (`scripts/apply_<topic>_output.py`)

워커 자체 수정 불필요. 1·3 만 새 작업마다 새로 짭니다.

---

## 9. 자주 묻는 질문

**Q. 다른 ChatGPT 프로젝트 컨텍스트(예: 후보자추천 프로젝트)에서 돌리고 싶다.**
A. `--start-url https://chatgpt.com/g/g-p-...` 옵션 또는 `.env` 의 `CHATGPT_PROJECT_URL` 설정.

**Q. 1000개를 더 빠르게.**
A. `--concurrency 10` 까지 안전. 그 이상은 ChatGPT 가 같은 계정에서 동시 응답 거절 가능.

**Q. 도중에 중단했다 재시작.**
A. `--resume` 옵션으로 같은 명령 그대로 재실행. 이미 `ok=true` 처리된 key 는 skip.

**Q. 응답 품질이 들쭉날쭉.**
A. 프롬프트에 (1) 역할 명시, (2) 출력 형식 예시, (3) "다른 텍스트 금지" 를 넣으세요. `--parse-json` 으로 1차 검증 가능.

**Q. ChatGPT 계정이 잠겼다.**
A. 일시적인 rate limit 차단입니다. 한 시간 정도 자동 풀립니다. 그동안 다른 작업으로 전환하세요.

---

## 10. 비교 — API 와 ChatGPT 멀티탭 워커

| 항목 | OpenAI API (`gpt-4o-mini`) | ChatGPT 멀티탭 워커 |
|---|---|---|
| 1000건 비용 | 약 $0.30 | $0 (구독료 외) |
| 모델 선택 | API 가능 모델만 | ChatGPT Plus/Pro 가 쓰는 최신 모델 사용 |
| 동시 처리 | 사실상 무제한 | 6~10 탭 |
| 1000건 처리 시간 | 1~3분 | 약 20~30분 |
| 결제 | $20 카드 | 이미 결제 중 |
| 적합한 경우 | 대용량·시간 민감 | 비용 0원 + 최신 모델 품질 |

호출자가 상황 보고 선택하세요. 본 skill 은 **ChatGPT 멀티탭 워커** 모드입니다.
