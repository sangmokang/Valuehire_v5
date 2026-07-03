# /humansearch Claude 스킬 등록 + 확장 스펙 5요건 SOT 반영 — goal (2026-07-02)

## 현재 상태 (직접 확인)
- 정본 스킬은 `skills/humansearch/SKILL.md` + `humansearch.config.json` (추적됨, 테스트 H1~H5).
- Claude Code 발동 심은 없었음 — `Skill("humansearch")` → "Unknown skill" (2026-07-02 세션 재현).
- `.claude/` 는 `.gitignore:19` 로 전체 무시 — aisearch 선례와 동일하게 발동 심은 **로컬 비추적**.
- 러너 `tools/multi_position_sourcing/humansearch_cdp_run.py:27-53` 은 포지션 하드코딩 —
  스크래치패드 런타임 오버라이드로 재사용(memory: humansearch-run-method).

## 핵심 질문
사장님 확장 스펙 5요건(반조립 URL 복수 / 포지션 복수 입력 / ClickUp 901818680208 등록 /
전부 저장 / Discord 814353841088757800 보고)을 **정본 SOT 에 기계 강제로** 박고,
`/humansearch` 가 실제로 발동되게 등록한다.

## 계약 (입출력)
- 입력: `{search_urls: [반조립 URL...], positions: [clickup_task_id|text|url ...]}`
- 출력: results.json(전 후보 raw) + DB upsert(ai_search_candidates, (url,position_id)) +
  ClickUp 부모 Task+합격 Subtask + Discord 중간/완료 보고 각 1건(+페이지당 1건).

## 인수 기준
1. (기계) H6 테스트 2개: SKILL.md 확장 마커 6종 존재 + config 신설 4섹션 스키마. → pytest
2. (기계) 전체 verify exit 0, 기존 테스트 약화 0.
3. (기계) 변이 시험: 채널 ID 제거·list_id 변조 시 테스트 FAIL (사살 확인).
4. (배선) `/humansearch` 가 available-skills 에 실제 등장(발동 심 `.claude/skills/humansearch/SKILL.md`).
5. (주관·수동) 스킬 본문이 실제 실행 절차(오늘 뤼튼·로보틱스 2회 실행 경험)와 일치.

## 적대검증 정조준
- H6 이 껍데기(문자열만)인가 — 마커 위치·의미 무관 통과 가능성.
- config 신설 섹션 vs 기존 섹션(output.channel=#ai_search vs reporting 채널) 모순.
- 기존 소비자(load_humansearch_config) 파손.

## 비범위
- 러너 파라미터화(하드코딩 해소) 코드 — 별도 조각(스크래치패드 오버라이드로 운영 중).
- 발동 심의 git 추적(.gitignore 정책 변경) — aisearch 선례 유지.
- 사람인·잡코리아 실제 병렬 순회 구현(SOT 명문화만; 실행은 기존 채널별 경로).

## 적대 검증 로그
- G 자기변이: SKILL.md 채널 ID 제거 → `1 failed`; config list_id 변조 → `1 failed`; 원복 → `58 passed`.
- V1(Codex): humansearch-claude-skill.verdict.json 참조.
