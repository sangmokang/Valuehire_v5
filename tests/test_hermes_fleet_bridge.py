from __future__ import annotations

import json

import pytest

from tools.multi_position_sourcing.hermes_fleet_bridge import (
    FLEET_PLUGIN_COMMANDS,
    HermesFleetBridgeError,
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


def test_clickup_plus_linkedin_url_rewrites_to_humansearch() -> None:
    rewritten = natural_fleet_command_text(
        "humansearch https://app.clickup.com/t/abc "
        "https://www.linkedin.com/search/results/people/?keywords=cto win"
    )
    assert rewritten == (
        "/fleet-run humansearch https://app.clickup.com/t/abc "
        "https://www.linkedin.com/search/results/people/?keywords=cto "
        "winpc"
    )


def test_direct_linkedin_url_rewrites_to_humansearch_without_fake_channels() -> None:
    rewritten = natural_fleet_command_text(
        "https://www.linkedin.com/search/results/people/?keywords=cto"
    )
    assert rewritten == (
        "/fleet-run humansearch "
        "https://www.linkedin.com/search/results/people/?keywords=cto"
    )


def test_direct_linkedin_profile_url_also_rewrites_to_humansearch() -> None:
    profile_url = "https://www.linkedin.com/in/example-candidate"
    assert natural_fleet_command_text(profile_url) == (
        f"/fleet-run humansearch {profile_url}"
    )


@pytest.mark.parametrize(
    ("url", "channel"),
    (
        (
            "https://www.saramin.co.kr/zf_user/memcom/talent-pool/main/search",
            "saramin",
        ),
        ("https://www.jobkorea.co.kr/Corp/Person/Find", "jobkorea"),
    ),
)
def test_direct_korean_portal_url_rewrites_to_humansearch(
    url: str, channel: str
) -> None:
    rewritten = natural_fleet_command_text(f"{url} win", message_id="42")
    assert rewritten == (
        f"/fleet-run humansearch {url} channels:{channel} winpc "
        "idempotency:discord:42"
    )


def test_direct_search_url_uses_recent_clickup_context_when_available() -> None:
    search_url = "https://www.linkedin.com/search/results/people/?keywords=cto"
    rewritten = natural_fleet_command_text(
        search_url,
        context_url="https://app.clickup.com/t/abc",
        context_channels=("saramin", "jobkorea"),
    )
    assert rewritten == (
        "/fleet-run humansearch https://app.clickup.com/t/abc "
        f"{search_url}"
    )


def test_direct_portal_url_dispatch_contract_preserves_search_urls() -> None:
    search_url = "https://www.linkedin.com/search/results/people/?keywords=cto"
    rewritten = natural_fleet_command_text(search_url, message_id="777")
    assert rewritten is not None
    options = parse_hermes_fleet_args(
        "fleet-run", rewritten.removeprefix("/fleet-run ")
    )
    assert options == {
        "skill": "humansearch",
        "url": search_url,
        "params": {
            "search_urls": [search_url],
            "idempotency_key": "discord:777",
            "execution": "live",
        },
    }


def test_win_without_position_context_does_not_enqueue() -> None:
    assert natural_fleet_command_text("win") is None


def test_unsupported_url_does_not_enqueue_even_with_humansearch_word() -> None:
    assert natural_fleet_command_text(
        "humansearch https://example.com/search/results/people"
    ) is None
    assert natural_fleet_command_text(
        "humansearch https://example.com/?next=linkedin.com/in/example"
    ) is None


def test_portal_url_is_not_required_to_have_clickup_context() -> None:
    assert natural_fleet_command_text(
        "https://www.saramin.co.kr/zf_user/memcom/talent-pool/main/search"
    ) == (
        "/fleet-run humansearch "
        "https://www.saramin.co.kr/zf_user/memcom/talent-pool/main/search "
        "channels:saramin"
    )


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


def test_slash_aisearch_lookalike_still_rewrites_to_fleet_run() -> None:
    # 2026-07-13 실사고: "/aisearch <url>" 는 실제 등록된 Hermes 명령이 아닌데
    # (등록 명령은 fleet-run/status/resume/cancel 뿐) 예전엔 맨 앞 "/" 만 보고
    # 통째로 None 을 반환해 자연어 변환을 못 타고 Hermes 일반 채팅으로 새서
    # skill 이 aisearch 대신 humansearch 로 잘못 추측·큐잉됐다(job #22).
    rewritten = natural_fleet_command_text(
        "/aisearch https://app.clickup.com/t/9018789656/86ey35mg3"
    )
    assert rewritten == (
        "/fleet-run aisearch https://app.clickup.com/t/9018789656/86ey35mg3 "
        "channels:saramin,jobkorea"
    )
    # 대소문자·앞뒤 공백에도 흔들리지 않는다.
    rewritten_upper = natural_fleet_command_text(
        "  /AISEARCH   https://app.clickup.com/t/9018789656/86ey35mg3  "
    )
    assert rewritten_upper == rewritten


def test_slash_humansearch_lookalike_still_rewrites_to_fleet_run() -> None:
    rewritten = natural_fleet_command_text(
        "/humansearch https://app.clickup.com/t/9018789656/86ey35mg3"
    )
    assert rewritten == (
        "/fleet-run aisearch https://app.clickup.com/t/9018789656/86ey35mg3 "
        "channels:saramin,jobkorea"
    )


def test_actually_registered_fleet_commands_are_not_rewritten() -> None:
    # fleet-run/status/resume/cancel 은 Hermes 가 이미 직접 dispatch 한다 —
    # pre_gateway_dispatch 훅에서 또 재작성하면 이중 처리가 된다.
    for command in FLEET_PLUGIN_COMMANDS:
        assert natural_fleet_command_text(
            f"/{command} https://app.clickup.com/t/abc"
        ) is None
    # 대소문자를 바꿔도 여전히 재작성하면 안 된다(등록 명령은 원래 Hermes 가 직접 처리).
    assert natural_fleet_command_text(
        "/FLEET-RUN https://app.clickup.com/t/abc"
    ) is None


def test_unregistered_slash_command_is_ignored_even_with_clickup_url() -> None:
    # 2026-07-13 Codex Rescue 2차 적대검증에서 발견: 첫 버전의 수정은 "등록된 4개
    # 명령이 아니면 다 통과"라서, "/help <클릭업 링크>"처럼 이 플러그인과 무관한 명령
    # (Hermes 게이트웨이 자체의 /help 등)에 우연히 클릭업 링크가 섞이면 의도치 않게
    # 진짜 fleet job 으로 하이재킹됐다. aisearch/humansearch 두 lookalike 만 명시
    # 허용목록으로 뚫어야 하고, 그 외 "/무엇" 은 원래처럼 전부 거부해야 한다.
    assert natural_fleet_command_text("/help please") is None
    assert natural_fleet_command_text("/help https://example.com/article") is None
    assert natural_fleet_command_text(
        "/help https://app.clickup.com/t/abc"
    ) is None
    # 오타/구두점이 붙은 등록 명령 근사치도 재작성하지 않는다(등록 명령도 아니고
    # 허용목록에도 없으므로 그대로 거부).
    assert natural_fleet_command_text(
        "/fleet-run, https://app.clickup.com/t/abc"
    ) is None
    assert natural_fleet_command_text(
        "/unknown-plugin-command https://app.clickup.com/t/abc"
    ) is None


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
