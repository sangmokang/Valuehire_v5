# AI/Humansearch ClickUp Registration Goal — 2026-07-07

## Objective

AI Search와 Humansearch 결과를 ClickUp FY26AI_Search 보드에 기록할 때, 대상 리스트와 등록 게이트를 흔들리지 않게 고정한다.

Target list:
- Name: FY26AI_Search
- List ID: `901818680208`
- URL: `https://app.clickup.com/9018789656/v/li/901818680208`

## Risk

L3. ClickUp Task/Subtask 생성은 외부 시스템 쓰기다. 사장님이 현재 턴에서 명시 승인하기 전에는 dry-run/계획과 읽기 기반 중복검사까지만 허용한다.

## Acceptance Criteria

1. AI Search와 Humansearch 모두 FY26AI_Search list `901818680208`을 ClickUp 등록 단일 목적지로 사용한다.
2. 포지션 부모 Task는 생성 전 같은 리스트에서 중복검사하고, 있으면 재사용한다.
3. 후보 Subtask는 생성 전 같은 부모 아래 `profile_url`로 중복검사하고, 있으면 새로 만들지 않는다.
4. 후보는 `profile_url`, `score`, `why_fit`, `profile_summary` 출력 계약을 만족해야 한다.
5. 후보는 프로필 저장 증거(`screenshot`, `evidence_paths`, archive id 등)가 있어야 한다.
6. 저장 증거 누락, 중복검사 누락, list id 불일치, `profile_url` 무효는 fail-closed다.
7. 스킬 문서, SOT25 JSON/MD, humansearch config, 코드 테스트가 같은 계약을 가리킨다.

## Non-Goals

- 이번 변경은 실제 ClickUp 라이브 Task를 생성하지 않는다.
- 채널 검색, JD 평가, 후보 스코어링 알고리즘은 변경하지 않는다.
