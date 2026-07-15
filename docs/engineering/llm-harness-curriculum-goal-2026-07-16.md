# llm-harness-curriculum — LLM 하니스·루프 엔지니어링 강의 문서 goal (2026-07-16)

## 1. 현재 상태
- 사장님 지시(/strict): "LLM 기반 코드를 더 깊이 Harness 조이기 + Loop Engineering을 학습할 테마들과
  실제 구현 기반 강의 체계를 HTML로, 잘 짜인 코드 체계를 지속 업데이트."
- 과거 회수: docs/·메모리·git log에 강의/커리큘럼류 산출물 없음(신규). 문서 인용경로 계약 테스트의
  선례는 있음 — `tests/test_goal_coding_sot_preflight_prompt.py`.

## 2. 설계
- 산출물: `docs/learning/llm-harness-loop-engineering.html` — 7부 커리큘럼(입문→고급).
  모든 레슨이 실존 코드 인용(`data-ref` 속성)에 근거.
- "지속 업데이트"의 기계화: 인용 경로가 이동/삭제되면 계약 테스트가 RED → 문서 갱신 강제.
  새 패턴 merge 시 레슨 추가는 자기확장 규칙(harness.md:56)의 적용.

## 3. 인수 기준 (EARS)
- **AC1**: When `./verify.sh` 실행 시, then 강의 문서가 존재하고 인용 경로 전부 실존·내부 앵커 무결·
  태그 균형·인용 20개 이상을 `tests/test_learning_curriculum_doc.py`가 GREEN으로 판정해야 한다.
  - 검증: `.venv-playwright/bin/python -m pytest tests/test_learning_curriculum_doc.py -q`
  - counter-AC: 문서를 비우거나(인용 0) 가짜 경로를 인용해도 초록이면 가짜. (뮤테이션으로 반증)

## 4. 계약 스펙
- 입력: HTML 내 `data-ref="<repo 상대경로>"` 속성, `href="#앵커"`.
- 판정: (REPO/경로).exists() 전건 참 · 앵커→id 전건 해소 · 비-void 태그 균형 오류 0 · refs ≥ 20.

## 5. 비범위
- 외부 레퍼런스 URL 검증(부록에 "다음 업데이트에서 검증 후 보강" 명시 — 미확인 링크는 싣지 않음).
- Artifact 게시는 repo 밖 행위(merge 후 수행).

## 6. 검증 증거 (Gate 4a + R2)
- RED: 커밋 `test(RED)` — 문서 부재로 5 errors(AssertionError, import 오류 아님).
- 뮤테이션: 가짜 인용(`ghost/does-not-exist.py`) + 끊긴 앵커(`#part-ghost`) 주입 →
  `test_all_cited_code_paths_exist`·`test_internal_anchors_resolve` 정확히 2건 FAIL → 원복 → 5 passed.
- 전체 verify: (아래 실행 출력 첨부)

## 적대 검증 로그
(아래에 V1 판정 append)
