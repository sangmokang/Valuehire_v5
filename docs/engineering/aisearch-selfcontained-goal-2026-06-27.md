# goal — aisearch 스킬 self-contained 화 (옵션 A) + 의존성 전수 조사

- 날짜: 2026-06-27
- 모드: code-change · 위험등급 L3 (파일 들여오기 + 스킬 동작 변경 + 파괴 가능성 검토)
- 생성자(G): Claude / V1: codex fresh / V2: Claude reset
- 절차 SOT: `~/.claude/skills/skill-creator/SKILL.md` (스킬 작업 = R6)
- 레포 SOT 읽음: `CLAUDE.md`, `docs/harness.md`, `docs/sot/22~26`, 메모리 `aisearch-skill-registration` 외

## 현재 상태 (직접 확인)
- 스킬 위치: `/Users/kangsangmo/Valuehire_v5/.claude/skills/aisearch/` (파일 2개: `SKILL.md`, `candidate-output-contract.json`)
- `.claude/`는 `.gitignore:19`로 **git 미추적** → 이 스킬은 머신-로컬 아티팩트(레포 배포물 아님).
- `SKILL.md`는 알맹이를 포인터로만 가리킴. 가리키는 곳:
  - 레포 내부(공유 자산): `docs/sot/22~26`, `docs/harness.md`, `tools/multi_position_sourcing/`, `skills/search`, `skills/multisearch`, `CLAUDE.md`, `candidate-output-contract.json`(폴더 내)
  - 레포 외부(HOME, git 미추적): `~/.codex/skills/ai-search/scripts/ai_search_sot_check.py`, `~/.claude/skills/linkedin-rps-jd-set-builder/SKILL.md`

## 핵심 질문
aisearch가 **다른 폴더(특히 HOME 스코프) 없이 자기 폴더만으로 동작**하게 만들되, 레포 공유 자산을 부수지 않는다.

## 근본 원인 (변동성)
진짜 변동성의 원인 = 레포 밖·git 미추적 파일 2개에 대한 의존. 머신/체크아웃이 바뀌면 그 2개가 없어 동작/검증이 깨진다.

## 비범위 (왜 옮기지 않나)
- `tools/multi_position_sourcing/` = 실행 엔진. 테스트 ~25개 + 내부 모듈이 import. 폴더로 옮기면 레포 전체 파손 + 단독 실행 불가 → **옮기지 않음(공유 유지)**.
- `docs/sot/22~26` = 다른 스킬 4개(search·multisearch·humansearch·position-registration) + 테스트 3개 공유 정본 → **옮기지 않음(공유 유지)**.
- git 추적 `tests/test_skill_reference_integrity.py`에 `.claude/` 경로 추가 금지(CI 재파손 유발).

## 인수 기준 (기계 검사 가능)
1. `.claude/skills/aisearch/SKILL.md`에 `~/.codex` 및 `~/.claude` 문자열이 **0건**이어야 한다(폴더 내 vendor 경로로 대체).
2. `.claude/skills/aisearch/vendor/`에 들여온 파일이 **존재 + 비어있지 않음**: `ai_search_sot_check.py`, `linkedin-rps-jd-set-builder.md`.
3. 폴더 자체 점검 스크립트 `vendor/check_self_contained.py` 실행 시 exit 0(외부 HOME 참조 0 + vendor 파일 존재 확인).
4. 레포 공유 자산 원본은 **그대로 존재**(docs/sot/22~26, tools/multi_position_sourcing, skills/search, skills/multisearch 삭제 0건).
5. 레포 `./verify.sh` (또는 `pytest tests/`) 기존 통과 수치 유지(회귀 없음).

## 적용 게이트
0 과거회수 + skill-creator 로드 / 0.5 worktree(docs용) + 라이브 .claude 편집 / 1 스펙(본 문서) / 2 RED(자체점검 스크립트가 현재 SKILL.md에서 실패) / 3 GREEN / 4 verify / 5 보고 / V1 codex 적대검증.

## 적대검증 정조준 항목
- vendor 복사본이 codex 정본과 드리프트하지 않는지(복사 시점·해시 기록).
- SKILL.md가 vendor 파일을 실제로 가리키는지(고아 vendor 금지 = R4 배선).
- 자체 점검 스크립트가 가짜 GREEN이 아닌지(RED 먼저 증명).
- 레포 공유 자산 무삭제(인수기준 4) 실측.

## 적대 검증 로그
(여기에 V1/V2 채움)
