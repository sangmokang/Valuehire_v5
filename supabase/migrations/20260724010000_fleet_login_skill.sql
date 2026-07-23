-- #188 — 큐 허용 스킬에 `login` 추가 (2026-07-24)
--
-- 왜: 사장님 지시(로그인은 Codex 실행) — /login 이 큐 정식 잡이 된다.
--     테이블 check 제약이 login 을 거부하면 파이썬 화이트리스트를 넓혀도
--     라이브 등록이 실패한다(Codex V2 F1 실측).
--
-- 원칙 유지: 화이트리스트를 없애는 게 아니라 한 칸 넓힌다(E24 — 목록 확장).
-- login 은 발송성 능력이 아니다: SOT26 계약상 검색·수집·발송을 하지 않는다.
--
-- 짝 갱신(부분 갱신 방지):
--   tools/multi_position_sourcing/job_queue.py           FLEET_SKILLS (+login)
--   tools/multi_position_sourcing/job_queue.py           FOLLOWUP_SKILLS (login 제외)
--   .claude/hooks/guards/discord-bot-skill-whitelist.py  _ALLOWED_SKILLS (이미 login 포함)
--   tests/test_fleet_login_job.py                        계약 테스트
--
-- 비범위: discord_gateway_enqueue(최소권한 RPC) 화이트리스트 확장은 게이트웨이
--        후속 이슈에서 별도 마이그레이션으로 다룬다(디스코드 /login 라이브 접수는
--        그 작업까지 끝나야 열린다).

alter table public.jobs drop constraint if exists jobs_skill_check;
alter table public.jobs
  add constraint jobs_skill_check
  check (skill in ('humansearch', 'aisearch', 'url', 'agent', 'jdintake', 'login'));

-- login 은 대상 URL 이 없는 스킬 — 빈 문자열('')을 login 에만 허용한다.
-- (파이썬 new_job_payload 의 login 전용 빈 URL 허용과 1:1 짝. 다른 스킬의
--  URL 규칙은 기존 정규식 그대로 — 약화 아님, login 한정 예외.)
alter table public.jobs drop constraint if exists jobs_position_url_http_chk;
alter table public.jobs add constraint jobs_position_url_http_chk
  check (
    (skill = 'login' and position_url = '')
    or (
      position_url ~ '^https?://[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?(:[0-9]{1,5})?([/?#].*)?$'
      and position_url !~ '\s'
      and substring(position_url from '^https?://([^/?#:]+)') !~ '\.\.'
      and (
        position_url !~ '^https?://[^/?#]*:[0-9]'
        or (substring(position_url from '^https?://[^/?#:]+:([0-9]{1,5})'))::int between 1 and 65535
      )
    )
  );
