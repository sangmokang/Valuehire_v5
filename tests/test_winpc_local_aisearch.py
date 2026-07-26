"""Owner-explicit WinPC AI Search must execute locally without a fleet queue."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.multi_position_sourcing import winpc_local_aisearch
from tools.multi_position_sourcing.fleet_worker import (
    build_codex_exec_args,
    build_job_prompt,
)


CLICKUP_URL = "https://app.clickup.com/t/9018789656/86ey90v4k"


def _search_receipt() -> str:
    channel = {
        "login_verified": True,
        "query_verified": True,
        "result_count_verified": True,
        "pages_visited": 1,
        "last_page_reached": True,
        "opened_profiles": 0,
        "saved_receipts": 0,
        "candidates": [],
    }
    return (
        "로컬 검색 완료\nFLEET_SEARCH_RECEIPT:"
        + json.dumps({"channels": {"saramin": channel}}, ensure_ascii=False)
    )


def test_local_request_is_bound_to_winpc_and_never_builds_queue_payload() -> None:
    request = winpc_local_aisearch.LocalAisearchRequest(
        position_url=CLICKUP_URL,
        channels=("saramin",),
        requested_by="owner-local",
        job_id=215,
    )

    job = request.as_job()

    assert job["machine"] == "winpc"
    assert job["skill"] == "aisearch"
    assert job["params"]["execution"] == "live"
    assert job["params"]["queue_mode"] == "none"
    assert "JobQueueClient" not in Path(winpc_local_aisearch.__file__).read_text(
        encoding="utf-8"
    )
    prompt = build_job_prompt(job)
    assert "WinPC 등록 관리 프로필" in prompt
    assert "Chrome Profile 2" not in prompt
    assert "~/.valuehire/login_receipts/<channel>.json" in prompt
    assert "portal_session_status_latest.json" not in prompt


def test_live_local_run_prepares_browser_and_invokes_agent_on_same_process_path(
    tmp_path: Path,
) -> None:
    calls: list[tuple[str, object]] = []

    def prepare(channels, *, environ):
        calls.append(("prepare", (channels, environ["VALUEHIRE_MACHINE"])))
        return {"status": "ready", "channels": list(channels)}

    def runner(prompt, timeout, *, env):
        calls.append(("runner", (timeout, env["VALUEHIRE_MACHINE"])))
        assert winpc_local_aisearch.LOCAL_EXECUTOR_MARKER in prompt
        assert "Do not invoke winpc_local_aisearch" in prompt
        assert "winpc_local_portal" in prompt
        assert "--probe" in prompt
        assert "top-level channels (not channel_receipts)" in prompt
        assert "port 9222" in prompt
        assert "portal_session_status_latest.json" in prompt
        assert env["VALUEHIRE_OWNER_LOCAL_AI_SEARCH"] == "1"
        assert env["VALUEHIRE_JOB_SKILL"] == "aisearch"
        assert env["VALUEHIRE_JOB_ROLE"] == "owner"
        args = build_codex_exec_args(env)
        pairs = list(zip(args, args[1:]))
        assert ("--sandbox", "workspace-write") in pairs
        assert ("--add-dir", str(Path.home() / ".valuehire")) in pairs
        assert ("--add-dir", str(Path.home() / ".vh-browser-evidence")) in pairs
        assert "sandbox_workspace_write.network_access=true" in args
        return _search_receipt(), "", 0

    result = winpc_local_aisearch.run_local_aisearch(
        winpc_local_aisearch.LocalAisearchRequest(
            position_url=CLICKUP_URL,
            channels=("saramin",),
            job_id=215,
        ),
        artifact_root=tmp_path / "runs",
        lock_path=tmp_path / "local.lock",
        environ={"LOCALAPPDATA": r"C:\Users\Test\AppData\Local"},
        portal_preparer=prepare,
        runner=runner,
        task_loader=lambda _url, *, environ: {
            "id": "86ey90v4k",
            "name": "Backend engineer",
            "description": "Python backend",
            "status": "open",
            "source_url": CLICKUP_URL,
        },
        system_name="Windows",
    )

    assert result.status == "done"
    assert result.machine == "winpc"
    assert calls == [
        ("prepare", (("saramin",), "winpc")),
        ("runner", (winpc_local_aisearch.LOCAL_SEARCH_TIMEOUT_SECONDS, "winpc")),
    ]


def test_clickup_task_context_is_bounded_and_does_not_return_token() -> None:
    seen: dict[str, object] = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self, limit):
            seen["limit"] = limit
            return json.dumps(
                {
                    "id": "86ey90v4k",
                    "name": "Backend engineer",
                    "description": "Python and Spring backend",
                    "status": {"status": "open"},
                }
            ).encode()

    def urlopen(request, *, timeout):
        seen["url"] = request.full_url
        seen["authorization"] = request.get_header("Authorization")
        seen["timeout"] = timeout
        return Response()

    context = winpc_local_aisearch._fetch_clickup_task_context(
        CLICKUP_URL,
        environ={"CLICKUP_API_TOKEN": "top-secret-token"},
        urlopen=urlopen,
    )

    assert context["id"] == "86ey90v4k"
    assert context["description"] == "Python and Spring backend"
    assert "top-secret-token" not in json.dumps(context)
    assert seen == {
        "url": "https://api.clickup.com/api/v2/task/86ey90v4k",
        "authorization": "top-secret-token",
        "timeout": 20,
        "limit": winpc_local_aisearch._MAX_CLICKUP_RESPONSE_BYTES + 1,
    }


def test_local_portal_preparation_refreshes_current_dom_even_with_fresh_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        winpc_local_aisearch,
        "ensure_windows_portal_browser",
        lambda channel, *, environ: {"channel": channel, "started": False},
    )
    monkeypatch.setattr(
        winpc_local_aisearch.login_barrier,
        "job_block_reason",
        lambda *_args, **_kwargs: None,
    )

    def login(channel, *, environ):
        calls.append(channel)
        return {"state": "AUTHENTICATED"}

    monkeypatch.setattr(winpc_local_aisearch, "_login_subprocess", login)

    result = winpc_local_aisearch.prepare_local_portals(
        ("saramin",),
        environ={},
    )

    assert result["status"] == "ready"
    assert calls == ["saramin"]


def test_production_receipt_is_derived_from_local_helper_artifact(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "runs" / "job-218"

    def runner(_prompt, _timeout, *, env):
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "portal-saramin.json").write_text(
            json.dumps(
                {
                    "status": "done",
                    "login_verified": True,
                    "query_verified": True,
                    "result_count_verified": True,
                    "pages_visited": 1,
                    "last_page_reached": True,
                    "opened_profiles": 0,
                    "saved_receipts": 0,
                    "profile_evidence": [],
                }
            ),
            encoding="utf-8",
        )
        return (
            'FLEET_SEARCH_RECEIPT:{"channel_receipts":{"saramin":{}}}',
            "",
            0,
        )

    result = winpc_local_aisearch.run_local_aisearch(
        winpc_local_aisearch.LocalAisearchRequest(
            position_url=CLICKUP_URL,
            channels=("saramin",),
            job_id=218,
        ),
        artifact_root=tmp_path / "runs",
        lock_path=tmp_path / "local.lock",
        environ={"LOCALAPPDATA": r"C:\Users\Test\AppData\Local"},
        portal_preparer=lambda channels, *, environ: {"status": "ready"},
        runner=runner,
        task_loader=lambda _url, *, environ: {
            "id": "86ey90v4k",
            "name": "Backend engineer",
            "description": "Python backend",
            "status": "open",
            "source_url": CLICKUP_URL,
        },
        system_name="Windows",
    )

    receipt = json.loads((run_dir / "receipt.json").read_text(encoding="utf-8"))
    assert result.status == "done"
    assert receipt["receipt"]["position_id"] == "86ey90v4k"
    assert set(receipt["receipt"]["channels"]) == {"saramin"}


def test_dry_run_has_no_browser_login_agent_or_queue_side_effect(
    tmp_path: Path,
) -> None:
    calls: list[str] = []

    def forbidden(*_args, **_kwargs):
        calls.append("external")
        raise AssertionError("dry-run external call")

    result = winpc_local_aisearch.run_local_aisearch(
        winpc_local_aisearch.LocalAisearchRequest(
            position_url=CLICKUP_URL,
            channels=("saramin",),
            job_id=216,
        ),
        dry_run=True,
        artifact_root=tmp_path / "runs",
        lock_path=tmp_path / "local.lock",
        portal_preparer=forbidden,
        runner=forbidden,
        system_name="Windows",
    )

    assert result.status == "dry_run"
    assert calls == []


def test_non_windows_local_entrypoint_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="Windows"):
        winpc_local_aisearch.run_local_aisearch(
            winpc_local_aisearch.LocalAisearchRequest(
                position_url=CLICKUP_URL,
                channels=("saramin",),
                job_id=217,
            ),
            dry_run=True,
            artifact_root=tmp_path,
            lock_path=tmp_path / "local.lock",
            system_name="Darwin",
        )


@pytest.mark.parametrize(
    "url",
    (
        "http://app.clickup.com/t/9018789656/86ey90v4k",
        "https://example.com/t/9018789656/86ey90v4k",
        "https://app.clickup.com/t/9018789656/86ey90v4k/extra",
        "https://owner:secret@app.clickup.com/t/9018789656/86ey90v4k",
        "https://app.clickup.com/t/9018789656/86ey90v4k%0A$other-skill",
    ),
)
def test_local_entrypoint_rejects_non_exact_or_injectable_clickup_url(url: str) -> None:
    with pytest.raises(ValueError, match="exact ClickUp"):
        winpc_local_aisearch.LocalAisearchRequest(position_url=url)


def test_local_run_lock_rejects_duplicate_process_on_same_winpc(tmp_path: Path) -> None:
    lock_path = tmp_path / "local.lock"

    with winpc_local_aisearch._LocalRunLock(lock_path):
        with pytest.raises(winpc_local_aisearch.LocalAisearchBusy):
            with winpc_local_aisearch._LocalRunLock(lock_path):
                pass

    with winpc_local_aisearch._LocalRunLock(lock_path):
        assert lock_path.is_file()


def test_local_search_permission_marker_cannot_escalate_wrong_context() -> None:
    marker = {"VALUEHIRE_OWNER_LOCAL_AI_SEARCH": "1"}
    for env in (
        marker,
        {**marker, "VALUEHIRE_JOB_SKILL": "aisearch", "VALUEHIRE_JOB_ROLE": "member",
         "VALUEHIRE_MACHINE": "winpc"},
        {**marker, "VALUEHIRE_JOB_SKILL": "aisearch", "VALUEHIRE_JOB_ROLE": "owner",
         "VALUEHIRE_MACHINE": "macmini"},
    ):
        args = build_codex_exec_args(env)
        pairs = list(zip(args, args[1:]))
        assert ("--sandbox", "read-only") in pairs
        assert ("--add-dir", str(Path.home() / ".valuehire")) not in pairs
        assert ("--add-dir", str(Path.home() / ".vh-browser-evidence")) not in pairs


def test_ai_search_skill_routes_owner_explicit_winpc_to_local_entrypoint() -> None:
    repo = Path(__file__).resolve().parents[1]
    command = "tools.multi_position_sourcing.winpc_local_aisearch"
    for relative in (
        ".codex/skills/ai-search/SKILL.md",
        "skills/ai-search/SKILL.md",
    ):
        body = (repo / relative).read_text(encoding="utf-8")
        assert command in body
        assert "원격 큐" in body
        assert winpc_local_aisearch.LOCAL_EXECUTOR_MARKER in body
        assert "재호출" in body
        assert "위 실행기 표시가 없고" in body
        assert (
            "python .codex/skills/ai-search/scripts/ai_search_sot_check.py --repo ."
            in body
        )
