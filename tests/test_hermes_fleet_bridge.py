from __future__ import annotations

import json

import pytest

from tools.multi_position_sourcing.hermes_fleet_bridge import (
    FLEET_PLUGIN_COMMANDS,
    HermesFleetBridgeError,
    _is_search_url,
    dispatch_hermes_fleet_command,
    natural_fleet_command_text,
    parse_hermes_fleet_args,
)

OWNER = "814353841088757800"
TEAM_MEMBER = "1404643716320329728"


class FakeQueue:
    def __init__(self) -> None:
        self.enqueued = []
        self.resumed = []
        self.cancelled = []

    def enqueue(self, payload):
        self.enqueued.append(payload)
        return {"id": 41, **payload}

    def recent(self, limit):
        return [{"id": 41, "status": "queued"}]

    def resume(self, job_id):
        self.resumed.append(job_id)
        return {"id": job_id, "status": "queued"}

    def cancel(self, job_id, reason):
        self.cancelled.append((job_id, reason))
        return {"id": job_id, "status": "cancelled"}


def test_plugin_exposes_exactly_the_existing_four_fleet_commands() -> None:
    assert FLEET_PLUGIN_COMMANDS == (
        "fleet-run", "fleet-resume", "fleet-status", "fleet-cancel"
    )


def test_fleet_run_parses_only_known_fields_and_reuses_dispatch() -> None:
    queue = FakeQueue()
    result = dispatch_hermes_fleet_command(
        "fleet-run",
        "skill:humansearch url:https://app.clickup.com/t/abc machine:macmini",
        gateway_user_id=OWNER,
        queue=queue,
    )
    assert result["action"] == "enqueued"
    assert queue.enqueued[0]["skill"] == "humansearch"
    assert queue.enqueued[0]["machine"] == "macmini"


@pytest.mark.parametrize(
    ("command", "raw"),
    [
        ("fleet-status", "unexpected:value"),
        ("fleet-run", "skill:humansearch url:https://x.test machine:macmini extra:no"),
        ("fleet-resume", "job:1 extra:no"),
        ("unknown", ""),
    ],
)
def test_unknown_command_or_field_is_explicitly_rejected(command: str, raw: str) -> None:
    with pytest.raises(HermesFleetBridgeError):
        parse_hermes_fleet_args(command, raw)


def test_unclosed_quote_is_rejected_not_leaked_as_raw_valueerror() -> None:
    # self-attack: shlex.split 이 못 닫힌 따옴표에 raw ValueError를 던지는데, 그게 그대로
    # 새면 상위 계약(HermesFleetBridgeError만 던진다는 약속)이 깨진다.
    with pytest.raises(HermesFleetBridgeError):
        parse_hermes_fleet_args("fleet-run", "skill:humansearch url:'unterminated")


def test_duplicate_field_is_rejected_not_silently_overwritten() -> None:
    # self-attack: 같은 필드를 두 번 주면 뒷값이 앞값을 조용히 밀어낼 수 있다(스머글링) — 거부해야 함.
    with pytest.raises(HermesFleetBridgeError):
        parse_hermes_fleet_args(
            "fleet-run", "skill:humansearch skill:aisearch url:https://x.test machine:macmini"
        )


def test_team_member_can_run_and_view_status_but_not_resume_or_cancel() -> None:
    queue = FakeQueue()
    run = dispatch_hermes_fleet_command(
        "fleet-run",
        "skill:humansearch url:https://app.clickup.com/t/abc machine:macmini",
        gateway_user_id=TEAM_MEMBER,
        queue=queue,
    )
    status = dispatch_hermes_fleet_command(
        "fleet-status", "", gateway_user_id=TEAM_MEMBER, queue=queue
    )
    assert run["action"] == "enqueued"
    assert status["action"] == "status"
    for command in ("fleet-resume", "fleet-cancel"):
        denied = dispatch_hermes_fleet_command(
            command, "job:7", gateway_user_id=TEAM_MEMBER, queue=queue
        )
        assert denied["action"] == "denied_owner_only"


def test_missing_gateway_identity_is_rejected_not_assumed_owner() -> None:
    with pytest.raises(HermesFleetBridgeError, match="identity"):
        dispatch_hermes_fleet_command(
            "fleet-status", "", gateway_user_id="", queue=FakeQueue()
        )


def test_unlisted_user_is_denied() -> None:
    result = dispatch_hermes_fleet_command(
        "fleet-status", "", gateway_user_id="999999999999999999", queue=FakeQueue()
    )
    assert result["action"] == "denied"


def test_server_invocation_uses_channel_allowlist_instead_of_dm_bypass(monkeypatch) -> None:
    monkeypatch.setenv("DISCORD_ALLOWED_CHANNEL_IDS", "1512503222222222222")
    monkeypatch.delenv("DISCORD_ALLOWED_ROLE_IDS", raising=False)
    queue = FakeQueue()
    result = dispatch_hermes_fleet_command(
        "fleet-run",
        "url https://app.clickup.com/t/abc idempotency:discord:1512503999999999999",
        gateway_user_id=OWNER,
        invocation_context={
            "channel_id": "1512503041448743092",
            "guild_id": "1512503000000000000",
            "is_dm": False,
            "role_ids": (),
            "event_id": "1512503999999999999",
        },
        queue=queue,
    )
    assert result["action"] == "denied"
    assert queue.enqueued == []


def test_status_and_owner_actions_return_json_serializable_results() -> None:
    queue = FakeQueue()
    for command, raw in (("fleet-status", ""), ("fleet-resume", "job:7"), ("fleet-cancel", "job:8")):
        result = dispatch_hermes_fleet_command(
            command, raw, gateway_user_id=OWNER, queue=queue
        )
        json.dumps(result, ensure_ascii=False)


def test_default_access_doc_resolves_regardless_of_process_cwd(monkeypatch, tmp_path) -> None:
    # 라이브 적대검증(2026-07-13)에서 실제 발견: 돌아가는 Hermes 게이트웨이의 cwd 는
    # ~/.hermes 라 상대경로 "docs/search-access.md" 는 항상 못 찾는다. 레포 루트 기준
    # 절대경로로 파생해야 cwd 와 무관하게 동작한다.
    monkeypatch.chdir(tmp_path)  # 레포 밖 임의 디렉터리로 이동 — 상대경로였다면 여기서 깨진다
    result = dispatch_hermes_fleet_command(
        "fleet-status", "", gateway_user_id=OWNER, queue=FakeQueue()
    )
    assert result["action"] == "status"


def test_bare_url_alone_defaults_skill_aisearch_without_forcing_winpc() -> None:
    # 사장님 요청(2026-07-13): "그냥 /fleet-run 하고 클릭업 링크만 주면 서치하도록" —
    # skill:/machine: 없이 URL 하나만 줘도 aisearch/winpc 기본값으로 등록돼야 한다.
    options = parse_hermes_fleet_args("fleet-run", "https://app.clickup.com/t/abc")
    assert options["skill"] == "aisearch"
    assert options["url"] == "https://app.clickup.com/t/abc"
    assert "machine" not in options


def test_bare_url_dispatches_end_to_end_with_defaults() -> None:
    queue = FakeQueue()
    result = dispatch_hermes_fleet_command(
        "fleet-run", "https://app.clickup.com/t/abc", gateway_user_id=OWNER, queue=queue
    )
    assert result["action"] == "enqueued"
    assert queue.enqueued[0]["skill"] == "aisearch"
    assert queue.enqueued[0]["machine"] == "macmini"
    assert queue.enqueued[0]["position_url"] == "https://app.clickup.com/t/abc"


def test_bare_url_with_explicit_skill_override_still_works() -> None:
    options = parse_hermes_fleet_args("fleet-run", "skill:aisearch https://app.clickup.com/t/abc")
    assert options == {"skill": "aisearch", "url": "https://app.clickup.com/t/abc"}


def test_bare_machine_token_overrides_default() -> None:
    options = parse_hermes_fleet_args("fleet-run", "https://app.clickup.com/t/abc winpc")
    assert options == {"skill": "aisearch", "url": "https://app.clickup.com/t/abc", "machine": "winpc"}


def test_win_alias_maps_to_winpc() -> None:
    options = parse_hermes_fleet_args("fleet-run", "https://app.clickup.com/t/abc win")
    assert options["machine"] == "winpc"


def test_bare_skill_token_also_accepted() -> None:
    options = parse_hermes_fleet_args("fleet-run", "https://app.clickup.com/t/abc aisearch")
    assert options == {"skill": "aisearch", "url": "https://app.clickup.com/t/abc"}


def test_bare_url_conflicting_with_explicit_url_key_is_rejected() -> None:
    with pytest.raises(HermesFleetBridgeError):
        parse_hermes_fleet_args(
            "fleet-run", "url:https://a.test https://b.test"
        )


def test_clickup_and_linkedin_urls_preserve_search_url_in_params() -> None:
    options = parse_hermes_fleet_args(
        "fleet-run",
        "https://app.clickup.com/t/abc https://www.linkedin.com/search/results/people/?keywords=cto",
    )
    assert options["url"] == "https://app.clickup.com/t/abc"
    assert options["params"] == {
        "search_urls": ["https://www.linkedin.com/search/results/people/?keywords=cto"]
    }


def test_search_result_url_alongside_position_url_selects_humansearch() -> None:
    # 2026-07-14 사장님 요청: 채용포털 검색결과 리스트 URL을 주면 humansearch가
    # 자동으로 발동해야 한다 — 검색결과 판정(_is_search_url)은 이미 있었지만 skill
    # 선택에 배선되어 있지 않았다(버그).
    options = parse_hermes_fleet_args(
        "fleet-run",
        "https://app.clickup.com/t/abc https://www.linkedin.com/search/results/people/?keywords=cto",
    )
    assert options["skill"] == "humansearch"


def test_position_url_alone_without_search_url_stays_aisearch() -> None:
    # 회귀 방지: 검색결과 URL이 전혀 없으면 기존 기본값(aisearch)이 그대로 유지돼야 한다.
    options = parse_hermes_fleet_args("fleet-run", "https://app.clickup.com/t/abc")
    assert options["skill"] == "aisearch"


def test_explicit_skill_override_wins_over_search_url_inference() -> None:
    # 사용자가 skill:aisearch를 명시했으면, 검색결과 URL이 있어도 추론이 그걸 덮어쓰면
    # 안 된다 — 명시 지정이 항상 이긴다.
    options = parse_hermes_fleet_args(
        "fleet-run",
        "skill:aisearch https://app.clickup.com/t/abc "
        "https://www.saramin.co.kr/zf_user/memcom/talent-pool/main/search",
    )
    assert options["skill"] == "aisearch"


def test_multiple_search_result_urls_all_preserved_for_humansearch_traversal() -> None:
    # "URL 리스트를 순회" 요구사항: 검색결과 URL이 여러 개면 전부 순서대로 남아야 한다.
    options = parse_hermes_fleet_args(
        "fleet-run",
        "https://app.clickup.com/t/abc "
        "https://www.saramin.co.kr/zf_user/memcom/talent-pool/main/search?q=1 "
        "https://www.jobkorea.co.kr/Corp/Person/Find?q=2",
    )
    assert options["skill"] == "humansearch"
    assert options["params"]["search_urls"] == [
        "https://www.saramin.co.kr/zf_user/memcom/talent-pool/main/search?q=1",
        "https://www.jobkorea.co.kr/Corp/Person/Find?q=2",
    ]


def test_search_result_url_dispatches_end_to_end_as_humansearch_job() -> None:
    # 자연어/명령 두 경로가 아니라 실제 큐잉 결과(dispatch_hermes_fleet_command)까지
    # humansearch로 들어가는지 — 배선이 절반만 되는 회귀를 잡는다.
    queue = FakeQueue()
    result = dispatch_hermes_fleet_command(
        "fleet-run",
        "https://app.clickup.com/t/abc "
        "https://www.linkedin.com/search/results/people/?keywords=cto",
        gateway_user_id=OWNER,
        queue=queue,
    )
    assert result["action"] == "enqueued"
    assert queue.enqueued[0]["skill"] == "humansearch"


def test_is_search_url_rejects_query_string_and_lookalike_domain() -> None:
    # 2026-07-14 Codex Rescue 적대검증 발견: 마커 문자열이 URL 아무데나(쿼리 문자열,
    # 유사 도메인) 있어도 True였다 — 호스트명이 진짜 그 도메인/서브도메인일 때만 True여야 함.
    assert _is_search_url("https://app.clickup.com/t/abc?source=jobkorea.co.kr") is False
    assert _is_search_url("https://linkedin.com.evil.example/not-a-search") is False
    assert _is_search_url("https://example.test/?next=https://www.jobkorea.co.kr/Search/") is False
    assert _is_search_url("https://www.linkedin.com/search/results/people/?keywords=cto") is True
    assert _is_search_url("https://saramin.co.kr/") is True


def test_position_url_with_incidental_marker_in_query_stays_aisearch() -> None:
    # fix6: 쿼리 문자열에 우연히 마커가 들어간 포지션 URL이 humansearch로 잘못 바뀌던
    # 회귀(counter-AC 위반)를 잡는다.
    options = parse_hermes_fleet_args(
        "fleet-run", "https://app.clickup.com/t/abc?source=jobkorea.co.kr"
    )
    assert options["skill"] == "aisearch"


def test_natural_language_explicit_skill_prefix_wins_over_search_url_inference() -> None:
    # 2026-07-14 Codex Rescue 적대검증 발견: 자연어 경로는 문장 속 "skill:aisearch" 명시를
    # 무시하고 검색결과 URL이 있다는 이유로 humansearch로 덮어썼다 — 직접 명령 경로(이미
    # 명시 지정을 존중)와 판정이 갈라져 있던 결함.
    rewritten = natural_fleet_command_text(
        "skill:aisearch로 찾아줘 https://app.clickup.com/t/abc "
        "https://www.saramin.co.kr/zf_user/memcom/talent-pool/main/search?q=x"
    )
    assert rewritten is not None
    assert rewritten.startswith("/fleet-run aisearch ")


def test_natural_language_explicit_skill_prefix_wins_without_search_url() -> None:
    # 반대 방향: 검색결과 URL이 없는데 "skill:humansearch"를 명시했으면 그것도 존중해야
    # 한다 — 예전엔 URL 없다는 이유로 조용히 aisearch로 덮어썼다.
    rewritten = natural_fleet_command_text(
        "skill:humansearch로 찾아줘 https://app.clickup.com/t/abc"
    )
    assert rewritten is not None
    assert rewritten.startswith("/fleet-run humansearch ")


def test_natural_language_bare_skill_word_wins_over_search_url_inference() -> None:
    # "skill:" 접두사 없이 그냥 "aisearch"라는 단어만 문장에 있어도(직접 명령 경로의
    # bare skill 토큰과 동등하게) 검색결과 URL 추론보다 우선해야 한다.
    rewritten = natural_fleet_command_text(
        "aisearch로 찾아줘 https://app.clickup.com/t/abc "
        "https://www.saramin.co.kr/zf_user/memcom/talent-pool/main/search?q=x"
    )
    assert rewritten is not None
    assert rewritten.startswith("/fleet-run aisearch ")


def test_natural_language_search_url_end_to_end_selects_humansearch() -> None:
    # natural_fleet_command_text 가 만든 문자열을 다시 parse_hermes_fleet_args 에
    # 태워도 humansearch 로 귀결되는지 — 두 진입점이 같은 판정을 쓰는지 확인.
    rewritten = natural_fleet_command_text(
        "이 링크 사람인에서 찾아줘 https://app.clickup.com/t/abc "
        "https://www.saramin.co.kr/zf_user/memcom/talent-pool/main/search?q=x"
    )
    assert rewritten is not None
    command, raw_args = rewritten[1:].split(" ", 1)
    options = parse_hermes_fleet_args(command, raw_args)
    assert options["skill"] == "humansearch"


def test_two_position_urls_are_rejected_not_silently_dropped() -> None:
    with pytest.raises(HermesFleetBridgeError, match="포지션 URL"):
        parse_hermes_fleet_args("fleet-run", "https://a.test https://b.test")


def test_linkedin_only_uses_existing_default_account_binding() -> None:
    queue = FakeQueue()
    result = dispatch_hermes_fleet_command(
        "fleet-run",
        "https://www.linkedin.com/search/results/people/?keywords=cto",
        gateway_user_id=OWNER,
        queue=queue,
    )
    assert result["action"] == "enqueued"
    assert queue.enqueued[0]["machine"] == "macmini"


def test_natural_humansearch_message_rewrites_with_urls_and_win_alias() -> None:
    # 2026-07-14: 문장에 링크드인 검색결과 URL이 있으면 자연어 경로도 humansearch로
    # 바뀌어야 한다 — 예전엔 "humansearch"라고 말해도 항상 "aisearch"로 굳어 있었다(버그).
    rewritten = natural_fleet_command_text(
        "humansearch https://app.clickup.com/t/abc "
        "https://www.linkedin.com/search/results/people/?keywords=cto win"
    )
    assert rewritten == (
        "/fleet-run humansearch https://app.clickup.com/t/abc "
        "https://www.linkedin.com/search/results/people/?keywords=cto "
        "channels:saramin,jobkorea winpc"
    )


def test_portal_url_or_win_without_position_context_does_not_enqueue() -> None:
    assert natural_fleet_command_text(
        "https://www.saramin.co.kr/zf_user/memcom/talent-pool/main/search"
    ) is None
    assert natural_fleet_command_text("win") is None


def test_unrelated_url_does_not_hijack_normal_chat() -> None:
    assert natural_fleet_command_text("참고해줘 https://example.com/article") is None


def test_followup_uses_recent_context_for_30_minute_store_contract() -> None:
    rewritten = natural_fleet_command_text(
        "잡코리아도", context_url="https://app.clickup.com/t/abc",
        context_channels=("saramin",), message_id="123456789",
    )
    assert rewritten == (
        "/fleet-run aisearch https://app.clickup.com/t/abc channels:jobkorea "
        "idempotency:discord:123456789"
    )


def test_win_followup_requires_context_and_routes_only_when_explicit() -> None:
    assert natural_fleet_command_text("win") is None
    rewritten = natural_fleet_command_text(
        "win", context_url="https://app.clickup.com/t/abc", context_channels=("saramin",)
    )
    assert rewritten and rewritten.endswith("channels:saramin winpc")


def test_no_win_token_never_injects_winpc() -> None:
    rewritten = natural_fleet_command_text(
        "후보 찾아줘 https://app.clickup.com/t/abc"
    )
    assert rewritten and "winpc" not in rewritten


def test_channels_and_idempotency_become_job_params() -> None:
    options = parse_hermes_fleet_args(
        "fleet-run",
        "https://app.clickup.com/t/abc channels:saramin,jobkorea idempotency:discord:42",
    )
    assert options["params"] == {
        "channels": ["saramin", "jobkorea"],
        "idempotency_key": "discord:42",
        "execution": "live",
    }


def test_fleet_run_without_any_url_is_rejected_with_clear_message() -> None:
    with pytest.raises(HermesFleetBridgeError, match="url"):
        parse_hermes_fleet_args("fleet-run", "skill:humansearch machine:macmini")


def test_unrecognized_bare_word_is_still_rejected_not_guessed() -> None:
    # fail-closed: url/skill/machine 어디에도 안 맞는 맨 단어는 추측하지 않고 거부한다.
    with pytest.raises(HermesFleetBridgeError):
        parse_hermes_fleet_args("fleet-run", "https://app.clickup.com/t/abc some_random_word")


def test_uppercase_scheme_bare_url_not_silently_accepted() -> None:
    # self-attack: 대소문자 우회로 URL 판정을 피해가려는 시도 — 소문자 http(s):// 만 인정.
    with pytest.raises(HermesFleetBridgeError):
        parse_hermes_fleet_args("fleet-run", "HTTPS://app.clickup.com/t/abc")


def test_flexible_format_not_offered_to_other_commands() -> None:
    # fleet-status/resume/cancel 은 여전히 엄격 key:value 만 — bare 토큰 완화는 fleet-run 전용.
    with pytest.raises(HermesFleetBridgeError):
        parse_hermes_fleet_args("fleet-resume", "7")


def test_unexpected_internal_error_is_reported_not_leaked_as_raw_exception(monkeypatch) -> None:
    # self-attack: authorized_users 로딩이나 큐 호출에서 예상 못 한 예외(파일 I/O, 네트워크)가
    # 나면 조용한 무응답(Hermes 쪽 광역 except 가 삼킴) 대신 명시적 error dict 로 보고해야 한다.
    class ExplodingQueue:
        def enqueue(self, payload):
            raise RuntimeError("boom")

    result = dispatch_hermes_fleet_command(
        "fleet-run",
        "skill:humansearch url:https://x.test machine:macmini",
        gateway_user_id=OWNER,
        queue=ExplodingQueue(),
    )
    assert result["action"] == "error"
    assert "boom" in result["reason"]


# ── 이슈 A(2026-07-15 goal §1) — "링크드인" 트리거 → url→aisearch 순차 핸드오프 ──

def test_linkedin_word_with_position_url_routes_url_skill_with_followup() -> None:
    rewritten = natural_fleet_command_text(
        "https://career.wrtn.io/ko/o/172878 이 포지션 링크드인에서 찾아")
    assert rewritten is not None
    command, raw_args = rewritten[1:].split(" ", 1)
    options = parse_hermes_fleet_args(command, raw_args)
    assert options["skill"] == "url"
    assert options["url"] == "https://career.wrtn.io/ko/o/172878"
    assert options["params"]["followup_skill"] == "aisearch"


def test_linkedin_english_word_case_insensitive_same_routing() -> None:
    rewritten = natural_fleet_command_text(
        "https://career.wrtn.io/ko/o/172878 position LinkedIn search please")
    assert rewritten is not None
    command, raw_args = rewritten[1:].split(" ", 1)
    options = parse_hermes_fleet_args(command, raw_args)
    assert options["skill"] == "url"
    assert options["params"]["followup_skill"] == "aisearch"


def test_saramin_jobkorea_words_go_straight_to_aisearch_without_followup() -> None:
    # 링크드인과 달리 사전 준비(/url) 스킬이 없으므로 aisearch 직행 — 우선순위 고정
    rewritten = natural_fleet_command_text(
        "이 포지션 사람인이랑 잡코리아에서 찾아줘 https://app.clickup.com/t/abc")
    assert rewritten is not None
    command, raw_args = rewritten[1:].split(" ", 1)
    options = parse_hermes_fleet_args(command, raw_args)
    assert options["skill"] == "aisearch"
    assert "followup_skill" not in (options.get("params") or {})
    assert options["params"]["channels"] == ["saramin", "jobkorea"]


def test_explicit_skill_overrides_linkedin_rule() -> None:
    rewritten = natural_fleet_command_text(
        "skill:aisearch 링크드인 말고 이걸로 찾아줘 https://app.clickup.com/t/abc")
    assert rewritten is not None
    assert rewritten.startswith("/fleet-run aisearch ")
    assert "followup:" not in rewritten


def test_win_alias_and_linkedin_rule_apply_together() -> None:
    rewritten = natural_fleet_command_text(
        "Win 에서 링크드인 찾아줘 https://career.wrtn.io/ko/o/172878")
    assert rewritten is not None
    command, raw_args = rewritten[1:].split(" ", 1)
    options = parse_hermes_fleet_args(command, raw_args)
    assert options["skill"] == "url"
    assert options["machine"] == "winpc"
    assert options["params"]["followup_skill"] == "aisearch"


def test_bare_token_win_any_case_maps_to_winpc() -> None:
    # 이미 대소문자 무관 동작 — 회귀 방지 고정(goal §1 확인 항목)
    from tools.multi_position_sourcing.hermes_fleet_bridge import (
        _classify_bare_fleet_run_token,
    )
    assert _classify_bare_fleet_run_token("Win") == ("machine", "winpc")
    assert _classify_bare_fleet_run_token("WIN") == ("machine", "winpc")


def test_followup_field_rejects_unknown_skill() -> None:
    with pytest.raises(HermesFleetBridgeError):
        parse_hermes_fleet_args(
            "fleet-run", "https://app.clickup.com/t/abc followup:sendmail")


def test_linkedin_word_with_search_url_does_not_force_url_skill() -> None:
    # 검색결과 URL이 섞이면(사람이 준비한 리스트) 기존 humansearch 추론 유지 — 규칙 미적용
    rewritten = natural_fleet_command_text(
        "링크드인에서 찾아줘 https://app.clickup.com/t/abc "
        "https://www.linkedin.com/search/results/people/?keywords=cto")
    assert rewritten is not None
    assert rewritten.startswith("/fleet-run humansearch ")
    assert "followup:" not in rewritten


# ── 이슈 B(2026-07-15 goal §2) — fleet 잡 agent 선택(claude|codex) ──

def test_natural_codex_word_selects_codex_agent() -> None:
    rewritten = natural_fleet_command_text(
        "codex로 이 포지션 찾아줘 https://app.clickup.com/t/abc")
    assert rewritten is not None
    assert "agent:codex" in rewritten
    command, raw_args = rewritten[1:].split(" ", 1)
    options = parse_hermes_fleet_args(command, raw_args)
    assert options["params"]["agent"] == "codex"


def test_natural_without_codex_word_has_no_agent_key() -> None:
    rewritten = natural_fleet_command_text(
        "이 포지션 찾아줘 https://app.clickup.com/t/abc")
    assert rewritten is not None
    assert "agent:" not in rewritten
    command, raw_args = rewritten[1:].split(" ", 1)
    options = parse_hermes_fleet_args(command, raw_args)
    assert "agent" not in (options.get("params") or {})


def test_codex_inside_url_only_does_not_select_codex() -> None:
    # URL 문자열 안의 codex 는 트리거 아님 — 본문 단어만
    rewritten = natural_fleet_command_text(
        "이 포지션 찾아줘 https://app.clickup.com/t/codex99")
    assert rewritten is not None
    assert "agent:" not in rewritten


def test_explicit_agent_field_validated() -> None:
    options = parse_hermes_fleet_args(
        "fleet-run", "https://app.clickup.com/t/abc agent:codex")
    assert options["params"]["agent"] == "codex"
    with pytest.raises(HermesFleetBridgeError):
        parse_hermes_fleet_args(
            "fleet-run", "https://app.clickup.com/t/abc agent:gpt4")


def test_codex_embedded_in_latin_token_does_not_trigger() -> None:
    # V1(Codex) 반증 수용 — 라틴 토큰 속 부분문자열은 오탐("codex로" 조사는 허용)
    rewritten = natural_fleet_command_text(
        "precodexpost 이 포지션 찾아줘 https://app.clickup.com/t/abc")
    assert rewritten is not None
    assert "agent:" not in rewritten
    rewritten2 = natural_fleet_command_text(
        "codex로 이 포지션 찾아줘 https://app.clickup.com/t/abc")
    assert rewritten2 is not None and "agent:codex" in rewritten2
