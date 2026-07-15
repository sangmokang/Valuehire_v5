# Codex 사용자 브리핑 복구 + #107/동탄 AI Search 재개 프롬프트 — goal (2026-07-15)

## 목표

Codex가 사장님께 보내는 모든 사용자 브리핑(중간·차단·최종)을 Claude의 쉬운 한국어
원칙과 맞추고, 이슈 #107 마감 뒤 원래 화성·동탄 AI Search를 재개하는 복사용 프롬프트를 남긴다.

## 현재 상태 증거와 근본 원인

- `CLAUDE.md:8-23`은 사장님께 말할 때 항상 한국어로 쉽고 짧게 설명하라고 한다.
- `AGENTS.md:8-10`은 쉬운 보고를 최종 보고에만 한정한다.
- `docs/harness.md:80-81`도 배송 뒤 최종 보고만 `AGENTS.md`에 연결한다.
- `tests/`에는 `AGENTS.md`의 사용자 브리핑 범위를 지키는 계약 검사가 없다.
- 결과적으로 작업 내부 용어가 중간·차단 보고에 그대로 노출되고, 코드 작업용 미완료 장부가
  라이브 후보 검색 자체의 차단 사유처럼 전달됐다.

## 기존 사례 회수

- 메모리: `feedback_autonomous_execution_no_confirm.md` — 승인 뒤 불필요한 재확인 금지.
- 기존 코드: `scripts/harness/red-ledger.sh` — 저장소 작업의 미완료 상태 추적.
- 스킬·문서: `CLAUDE.md`, `docs/harness.md`, ai-search 스킬의 쉬운 한국어 보고 원칙.
- 계약검사 선례: `tests/test_sot_distrust_doublecheck_doc.py`의 문서 마커 검사.

## 단일 인수 기준

`test_p5_all_owner_briefings_and_two_stage_recovery_prompt` 하나가 다음을 함께 보장한다.

1. `AGENTS.md`가 중간·차단·최종 사용자 브리핑 전부에 적용된다.
2. 스킬·프롬프트의 기술 보고 형식보다 사용자용 쉬운 번역이 우선한다.
3. 중간·차단 보고는 현재 상태·이유·다음 행동, 최종 보고는 기존 5칸 형식을 쓴다.
4. `docs/harness.md`가 위 전 단계 계약을 실제 작업 절차에 연결한다.
5. 재사용 프롬프트가 #107을 검증·병합·장부 마감한 뒤 화성·동탄 AI Search를 재개한다.
6. 프롬프트가 사람인 추가 검색, LinkedIn 좌측 키워드·위치 필터, 후보 필수 4필드와
   발송 금지를 보존한다.

## 비범위

- 이슈 #107 코드 자체 수정·검증·병합
- 실제 사람인·잡코리아·LinkedIn 검색 및 후보 등록·발송
- Codex/Claude 전역 스킬 수정
- 커밋, push, PR 생성

## 검증 명령

```bash
PYTHONPATH=. /Volumes/SSD/valuehire_v5/.venv/bin/python -m pytest \
  tests/test_sot_distrust_doublecheck_doc.py::test_p5_all_owner_briefings_and_two_stage_recovery_prompt -q
./verify.sh
```

## SOT 체크리스트

- [ ] 사용자 브리핑에는 내부 용어를 그대로 노출하지 않는다.
- [ ] 내부 산출물의 기술 증거는 삭제하거나 약화하지 않는다.
- [ ] 정확히 5파일, 구현 변경 300줄 이내다.
- [ ] 테스트 삭제·skip·assertion 약화가 없다.
- [ ] 외부 쓰기와 발송이 없다.
