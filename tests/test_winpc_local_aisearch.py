"""Owner-explicit WinPC AI Search must execute locally without a fleet queue."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.multi_position_sourcing import winpc_local_aisearch


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


def test_live_local_run_prepares_browser_and_invokes_agent_on_same_process_path(
    tmp_path: Path,
) -> None:
    calls: list[tuple[str, object]] = []

    def prepare(channels, *, environ):
        calls.append(("prepare", (channels, environ["VALUEHIRE_MACHINE"])))
        return {"status": "ready", "channels": list(channels)}

    def runner(prompt, timeout, *, env):
        calls.append(("runner", (timeout, env["VALUEHIRE_MACHINE"])))
        assert "$ai-search" in prompt
        assert CLICKUP_URL in prompt
        return _search_receipt(), "", 0

    result = winpc_local_aisearch.run_local_aisearch(
        winpc_local_aisearch.LocalAisearchRequest(
            position_url=CLICKUP_URL,
            channels=("saramin",),
            job_id=215,
        ),
        artifact_root=tmp_path / "runs",
        lock_path=tmp_path / "local.lock",
        environ={"LOCALAPPDATA": str(tmp_path / "LocalAppData")},
        portal_preparer=prepare,
        runner=runner,
        system_name="Windows",
    )

    assert result.status == "done"
    assert result.machine == "winpc"
    assert calls == [
        ("prepare", (("saramin",), "winpc")),
        ("runner", (winpc_local_aisearch.LOCAL_SEARCH_TIMEOUT_SECONDS, "winpc")),
    ]


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

