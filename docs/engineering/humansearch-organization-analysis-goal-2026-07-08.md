# humansearch 조직 분석 저장/배치 동기화 goal (2026-07-08)

## 현재 상태
- `Position` 에 `organization_analysis` / `talent_density_notes` 필드는 이미 있다.
- `score_humansearch()` 는 후보 점수에 조직 맥락 보정을 넣고 있으나, 조직 분석을 sqlite에 먼저 누적하는 별도 저장 레일은 없었다.
- Supabase 미러는 후보 `profile_archives` / `sourcing_results` 중심이었다.

## 목표
1. 조직 분석을 sqlite 기본 저장소에 먼저 누적한다.
2. sqlite `organization_analysis` 를 배치로 Supabase `organization_analysis` 테이블에 미러한다.
3. humansearch 결과에 `org_fit` 라벨을 별도 필드로 노출한다.

## 인수 기준
- `score_humansearch()` / `format_discord_candidate_briefing()` 에서 `org_fit` 라벨이 보인다.
- sqlite `organization_analysis` 테이블에 `position_id` 단위 upsert 가 된다.
- `scripts/organization_analysis_supabase_backfill.py --dry-run` 이 sqlite rows 를 읽고 Supabase payload 수를 출력한다.
- `humansearch_supabase_sync.py` 가 organization analysis payload 를 생성한다.
- 테스트가 새 저장 레일과 `org_fit` 라벨을 고정한다.

## 비범위
- Supabase 스키마 실제 마이그레이션 실행
- 실시간 외부 랭킹/업계 순위 크롤링
- 후보 발송/등록 자동 실행

## 검증
- `PYTHONPATH=. pytest tests/test_humansearch_skill.py tests/test_humansearch_supabase_sync.py tests/test_reservoir_scoring.py`
- `python -m compileall tools/multi_position_sourcing/*.py scripts/organization_analysis_supabase_backfill.py`

## SOT 체크리스트
- 값은 sqlite 기본 저장소를 먼저 거친다.
- Supabase 미러는 batch/backfill 로만 수행한다.
- `org_fit` 는 점수와 분리된 라벨이다.
