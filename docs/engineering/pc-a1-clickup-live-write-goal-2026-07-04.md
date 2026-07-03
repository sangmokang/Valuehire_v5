# PC-A1 — ClickUp 실 쓰기 배선 + 목적지 리스트(FY26ClientsPosition) · goal

- 모드: code-change · 위험등급: **L2** (단일 파일 확장, 계약형 페이크 주입, 실제 외부 쓰기 없음·SOT3 발송 아님)
- 선행: PC-A0(목적지 list_id seam) — merged PR#62.

## 현재 상태 (직접 연 file:line)
- `tools/multi_position_sourcing/position_registration.py:215` `clickup_list_id: Optional[str] = None` (PC-A0 seam).
- `:291` `if clickup_list_id:` → create 경로에서만 어댑터에 목적지 전달.
- 코드 내 **FY26ClientsPosition 목적지 상수 없음**(`git grep 901814621569 -- tools/` → 0건). 프로덕션 호출자는 `dry_run.py:82`(dry_run=True, create_task 미주입)뿐.

## 핵심 질문
라이브 경로(dry_run=False, 비중복, confidence≥0.55)에서 포지션 인입이 **설정된 FY26ClientsPosition 목적지로 정확히 1회** create 되는가?

## 계약 (SDD)
- 신규 상수 `FY26_CLIENTS_POSITION_LIST_ID: str = "901814621569"` (출처: `docs/search-access.md:425`, `.claude/skills/url/SKILL.md:59` — 사장님 지정 FY26ClientsPosition 리스트). SOT5 단일출처.
- 입력: 샘플 JD(RICH_WANTED_HTML) + 페이크 http_fetch + 페이크 clickup_search(→[] 비중복) + 페이크 clickup_create_task + `clickup_list_id=FY26_CLIENTS_POSITION_LIST_ID` + dry_run=False.
- 출력 단언: `create_task` 호출 **정확히 1회**, 목적지 인자 == 리터럴 `"901814621569"`, `outcome.status=="created"`, `is_new_task`, `external_posting_sent is False`, `secret_emitted is False`.

## 인수 기준 (기계 검사)
- `verify.sh` exit 0.
- 통합테스트: 라이브 경로에서 FY26 목적지로 정확히 1회 create.
- 실패경로: 중복이면 create **0회**(코멘트 경로) — 목적지에 잘못된 신규 쓰기 없음.

## 적용 게이트
harness 0~6 + gate4b(G 자기 mutation + Codex V1). L2라 V2/3자대조는 비강제.

## 적대검증 정조준
- 상수 리터럴이 SOT(search-access.md:425)와 일치하는가(오타=잘못된 리스트에 쓰기).
- "정확히 1회"가 dedup·dry_run 분기에서 새지 않는가(2회/0회 오류).
- SOT3 불변식(external_posting_sent=False) 유지.
- 상수 고아 여부(소비: 통합테스트 now, PC-A3 디스패처 예정 — seam).

## 비범위
- 실제 ClickUp API writer(신규 clickup_writer.py 금지·SOT5). 라이브 MCP 쓰기.
- 커스텀필드 매퍼(PC-A2a) · 부모-자식 링크(PC-A2b) · Discord 디스패처(PC-A3).

## 적대 검증 로그
(verdict.json 에 축적)
