"""PC-F4b — live resident daemon wiring contract.

These tests cover only the machine-verifiable half of PC-F4b. They do not start
launchd, log in to portals, or attach to a real browser.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from tools.multi_position_sourcing import harvest_driver
from tools.multi_position_sourcing.harvest_runner import HarvestItem
from tools.multi_position_sourcing.portal_runtime import GuardedSearchResult

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "valuehire-search-loop.sh"
ZSH = shutil.which("zsh")
requires_zsh = pytest.mark.skipif(
    ZSH is None,
    reason="valuehire-search-loop.sh is zsh-only; skip on non-zsh CI images",
)


class _FakeRunner:
    def __init__(self, channel: str) -> None:
        self.channel = channel

    async def run_keyword_search(self, keyword: str, *, searches_today: int):
        return GuardedSearchResult(
            site=self.channel,
            worker_id="worker-1",
            keyword=keyword,
            status="searched",
            reason="ok",
            candidate_cards=(f"{self.channel}:{keyword}",),
        )


def test_build_guarded_runner_binds_channel_endpoint_without_starting_browser(tmp_path) -> None:
    worker_configs: list[Any] = []

    class FakeWorker:
        def __init__(self, config: Any) -> None:
            self.config = config
            worker_configs.append(config)

    class FakeGuardedRunner:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

        async def run_keyword_search(self, keyword: str, *, searches_today: int):
            raise AssertionError("factory unit test must not start a browser")

    runner = harvest_driver.build_guarded_runner(
        "jobkorea",
        worker_id="worker-7",
        profile_root=tmp_path / "profiles",
        chrome_cdp_endpoints={"jobkorea": "http://127.0.0.1:19224"},
        worker_cls=FakeWorker,
        runner_cls=FakeGuardedRunner,
        encryptor=object(),
        snapshot_store=object(),
        event_store=object(),
        snapshot_validator=lambda _state: True,
        ready_check_factory=lambda channel: f"ready:{channel}",
        sleep=None,
    )

    assert hasattr(runner, "run_keyword_search")
    assert len(worker_configs) == 1
    worker_config = worker_configs[0]
    assert worker_config.channel == "jobkorea"
    assert worker_config.worker_id == "worker-7"
    assert worker_config.profile_root == tmp_path / "profiles"
    assert worker_config.chrome_cdp_endpoint == "http://127.0.0.1:19224"
    assert runner.kwargs["worker"].config is worker_config
    assert runner.kwargs["ready_check"] == "ready:jobkorea"
    assert runner.kwargs["sleep"] is None


def test_build_live_execute_item_uses_injected_runner_factory(tmp_path) -> None:
    keywords_json = tmp_path / "keywords.json"
    keywords_json.write_text('{"it_ai_data": ["python"]}', encoding="utf-8")
    calls: list[str] = []

    def runner_for_channel(channel: str) -> _FakeRunner:
        calls.append(channel)
        return _FakeRunner(channel)

    executor = harvest_driver._build_live_execute_item(
        str(keywords_json),
        runner_for_channel=runner_for_channel,
    )
    found = asyncio.run(
        executor(HarvestItem(segment_id="it_ai_data", channel="saramin", machine="macmini"))
    )

    assert calls == ["saramin"]
    assert found == ("saramin:python",)


def _print_loop_command(extra_env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    env = {
        "VALUEHIRE_REPO_DIR": str(REPO_ROOT),
        "VALUEHIRE_SEARCH_LOOP_PRINT_COMMAND": "1",
        "PATH": "/usr/bin:/bin",
        **extra_env,
    }
    return subprocess.run(
        [ZSH, str(SCRIPT)],
        env=env,
        capture_output=True,
        text=True,
        timeout=5,
    )


@requires_zsh
def test_search_loop_default_command_stays_non_live() -> None:
    proc = _print_loop_command({})
    assert proc.returncode == 0, proc.stderr
    command = proc.stdout.strip()
    assert "tools.multi_position_sourcing.dry_run" in command
    assert "tools.multi_position_sourcing.harvest_driver" not in command
    assert "--executor live" not in command


@requires_zsh
def test_search_loop_live_flag_builds_harvest_driver_command(tmp_path) -> None:
    keywords_json = tmp_path / "keywords.json"
    keywords_json.write_text('{"it_ai_data": ["python"]}', encoding="utf-8")

    proc = _print_loop_command(
        {
            "VALUEHIRE_SEARCH_EXECUTOR": "live",
            "VALUEHIRE_SEARCH_SEGMENTS": "it_ai_data",
            "VALUEHIRE_SEARCH_MACHINE": "macmini",
            "VALUEHIRE_SEARCH_RUN_ID": "live-test",
            "VALUEHIRE_SEARCH_TODAY": "2026-07-07",
            "VALUEHIRE_SEARCH_KEYWORDS_JSON": str(keywords_json),
        }
    )

    assert proc.returncode == 0, proc.stderr
    command = proc.stdout.strip()
    assert "tools.multi_position_sourcing.harvest_driver" in command
    assert "--executor live" in command
    assert "--segments it_ai_data" in command
    assert "--machine macmini" in command
    assert "--run-id live-test" in command
    assert "--today 2026-07-07" in command
    assert f"--keywords-json {keywords_json}" in command
    assert "--skip-owner-check" not in command
    assert "tools.multi_position_sourcing.dry_run" not in command


@requires_zsh
def test_search_loop_fake_one_shot_smoke_writes_fake_executor_json(tmp_path) -> None:
    artifact_dir = tmp_path / "artifacts"
    log_dir = tmp_path / "logs"
    proc = subprocess.run(
        [ZSH, str(SCRIPT)],
        env={
            "VALUEHIRE_REPO_DIR": str(REPO_ROOT),
            "VALUEHIRE_ARTIFACT_DIR": str(artifact_dir),
            "VALUEHIRE_LOG_DIR": str(log_dir),
            "VALUEHIRE_SEARCH_EXECUTOR": "fake",
            "VALUEHIRE_SEARCH_LOOP_ONCE": "1",
            "VALUEHIRE_SEARCH_SKIP_OWNER_CHECK": "1",
            "VALUEHIRE_PYTHON_BIN": sys.executable,
            "VALUEHIRE_SEARCH_SEGMENTS": "it_ai_data",
            "VALUEHIRE_SEARCH_MACHINE": "macmini",
            "VALUEHIRE_SEARCH_RUN_ID": "fake-smoke",
            "VALUEHIRE_SEARCH_TODAY": "2026-07-07",
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        },
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert proc.returncode == 0, proc.stderr
    payload = (artifact_dir / "harvest-fake-latest.json").read_text(encoding="utf-8")
    assert '"executor": "fake"' in payload
