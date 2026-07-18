"""macOS 로그인 창을 exact CDP identity로 찾고 창 하나만 캡처하는 계약."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from tools.multi_position_sourcing import macos_window_locator as locator_module
from tools.multi_position_sourcing.macos_window_locator import (
    CdpWindowIdentity,
    WindowBounds,
    WindowResolutionError,
    activate_exact_macos_application,
    capture_exact_window_png,
    resolve_exact_macos_window,
)


def _completed(argv: list[str], *, stdout: str = "", returncode: int = 0):
    return subprocess.CompletedProcess(argv, returncode, stdout=stdout, stderr="")


def test_resolve_exact_window_uses_pid_marker_and_cdp_bounds_not_first_fallback() -> None:
    calls: list[list[str]] = []
    marker = "[LOGIN HERE][Codex][linkedin][target-abc123]"
    payload = [
        {
            "cg_window_id": 1,
            "owner_pid": 9999,
            "layer": 0,
            "title": marker,
            "bounds": {"left": 10, "top": 20, "width": 1200, "height": 800},
            "on_screen": True,
            "frontmost_layer0": False,
        },
        {
            "cg_window_id": 2,
            "owner_pid": 4321,
            "layer": 0,
            "title": marker,
            "bounds": {"left": 400, "top": 20, "width": 1200, "height": 800},
            "on_screen": True,
            "frontmost_layer0": False,
        },
        {
            "cg_window_id": 175,
            "owner_pid": 4321,
            "layer": 0,
            "title": marker + " LinkedIn Talent Solutions",
            "bounds": {"left": 10, "top": 20, "width": 1200, "height": 800},
            "on_screen": True,
            "frontmost_layer0": True,
        },
    ]

    def run(argv: list[str], **_kwargs):
        calls.append(list(argv))
        return _completed(argv, stdout=json.dumps(payload))

    identity = CdpWindowIdentity(
        browser_pid=4321,
        target_id="target-abc123",
        title_marker=marker,
        bounds=WindowBounds(left=10, top=20, width=1200, height=800),
    )
    resolved = resolve_exact_macos_window(
        identity,
        run_command=run,
        system_name="Darwin",
    )

    assert resolved.cg_window_id == 175
    assert resolved.owner_pid == 4321
    argv = calls[0]
    assert Path(argv[0]).name == "swift"
    assert ["--pid", "4321"] == argv[argv.index("--pid") : argv.index("--pid") + 2]
    assert marker in argv
    for value in ("10", "20", "1200", "800"):
        assert value in argv


def test_preflight_can_resolve_one_hidden_window_before_exact_app_activation() -> None:
    calls: list[list[str]] = []
    payload = [{
        "cg_window_id": 175,
        "owner_pid": 4321,
        "layer": 0,
        "title": "",
        "bounds": {"left": 10, "top": 20, "width": 1200, "height": 800},
        "on_screen": False,
        "frontmost_layer0": False,
    }]

    def run(argv: list[str], **_kwargs):
        calls.append(list(argv))
        return _completed(argv, stdout=json.dumps(payload))

    resolved = resolve_exact_macos_window(
        CdpWindowIdentity(
            browser_pid=4321,
            target_id="target-abc123",
            title_marker="",
            bounds=WindowBounds(left=10, top=20, width=1200, height=800),
        ),
        require_on_screen=False,
        run_command=run,
        system_name="Darwin",
    )

    assert resolved.cg_window_id == 175
    assert resolved.on_screen is False
    assert calls[0][calls[0].index("--require-on-screen") + 1] == "false"


def test_final_resolution_can_require_exact_window_is_frontmost_layer_zero() -> None:
    marker = "[LOGIN HERE][Codex][linkedin][target-abc123]"
    payload = [{
        "cg_window_id": 175,
        "owner_pid": 4321,
        "layer": 0,
        "title": marker + " LinkedIn Talent Solutions",
        "bounds": {"left": 10, "top": 20, "width": 1200, "height": 800},
        "on_screen": True,
        "frontmost_layer0": False,
    }]

    def run(argv: list[str], **_kwargs):
        return _completed(argv, stdout=json.dumps(payload))

    identity = CdpWindowIdentity(
        browser_pid=4321,
        target_id="target-abc123",
        title_marker=marker,
        bounds=WindowBounds(left=10, top=20, width=1200, height=800),
    )
    resolved = resolve_exact_macos_window(
        identity,
        run_command=run,
        system_name="Darwin",
    )
    assert resolved.frontmost_layer0 is False

    with pytest.raises(WindowResolutionError, match="exact window match count was 0"):
        resolve_exact_macos_window(
            identity,
            require_frontmost=True,
            run_command=run,
            system_name="Darwin",
        )

    payload[0]["frontmost_layer0"] = True
    resolved = resolve_exact_macos_window(
        identity,
        require_frontmost=True,
        run_command=run,
        system_name="Darwin",
    )
    assert resolved.cg_window_id == 175
    assert resolved.frontmost_layer0 is True


def test_frontmost_proof_and_requirement_fail_closed_for_wrong_types() -> None:
    marker = "[LOGIN HERE]"
    identity = CdpWindowIdentity(
        browser_pid=4321,
        target_id="target",
        title_marker=marker,
        bounds=WindowBounds(left=0, top=0, width=10, height=10),
    )
    payload = [{
        "cg_window_id": 175,
        "owner_pid": 4321,
        "layer": 0,
        "title": marker,
        "bounds": {"left": 0, "top": 0, "width": 10, "height": 10},
        "on_screen": True,
        "frontmost_layer0": 1,
    }]
    calls: list[list[str]] = []

    def run(argv: list[str], **_kwargs):
        calls.append(list(argv))
        return _completed(argv, stdout=json.dumps(payload))

    with pytest.raises(WindowResolutionError, match="exact window match count was 0"):
        resolve_exact_macos_window(identity, run_command=run, system_name="Darwin")
    with pytest.raises(WindowResolutionError, match="require_frontmost must be boolean"):
        resolve_exact_macos_window(
            identity,
            require_frontmost=1,  # type: ignore[arg-type]
            run_command=run,
            system_name="Darwin",
        )
    assert len(calls) == 1


def test_activate_exact_application_uses_only_bound_browser_pid() -> None:
    calls: list[list[str]] = []

    def run(argv: list[str], **_kwargs):
        calls.append(list(argv))
        return _completed(argv, stdout=json.dumps({"activated": True, "pid": 4321}))

    assert activate_exact_macos_application(
        4321,
        run_command=run,
        system_name="Darwin",
    ) is True
    assert calls == [[
        "swift",
        str(Path(__file__).resolve().parents[1] / "skills/login/scripts/macos_window_locator.swift"),
        "--activate-pid",
        "4321",
    ]]


@pytest.mark.parametrize(
    ("stdout", "returncode"),
    [
        ("[]", 0),
        (
            json.dumps(
                [
                    {
                        "cg_window_id": 175,
                        "owner_pid": 4321,
                        "layer": 0,
                        "title": "[LOGIN HERE]",
                        "bounds": {"left": 0, "top": 0, "width": 10, "height": 10},
                        "on_screen": True,
                        "frontmost_layer0": True,
                    },
                    {
                        "cg_window_id": 176,
                        "owner_pid": 4321,
                        "layer": 0,
                        "title": "[LOGIN HERE]",
                        "bounds": {"left": 0, "top": 0, "width": 10, "height": 10},
                        "on_screen": True,
                        "frontmost_layer0": False,
                    },
                ]
            ),
            0,
        ),
        ("not-json", 0),
        ("", 1),
    ],
)
def test_resolve_exact_window_fails_closed_for_zero_ambiguous_malformed_or_command_error(
    stdout: str,
    returncode: int,
) -> None:
    identity = CdpWindowIdentity(
        browser_pid=4321,
        target_id="target",
        title_marker="[LOGIN HERE]",
        bounds=WindowBounds(left=0, top=0, width=10, height=10),
    )

    def run(argv: list[str], **_kwargs):
        return _completed(argv, stdout=stdout, returncode=returncode)

    with pytest.raises(WindowResolutionError):
        resolve_exact_macos_window(identity, run_command=run, system_name="Darwin")


def test_non_darwin_never_invokes_swift_or_screencapture() -> None:
    calls: list[list[str]] = []

    def run(argv: list[str], **_kwargs):
        calls.append(list(argv))
        raise AssertionError("platform fail-close must happen before subprocess")

    identity = CdpWindowIdentity(
        browser_pid=1,
        target_id="target",
        title_marker="[LOGIN HERE]",
        bounds=WindowBounds(left=0, top=0, width=10, height=10),
    )
    with pytest.raises(WindowResolutionError):
        resolve_exact_macos_window(identity, run_command=run, system_name="Linux")
    with pytest.raises(WindowResolutionError):
        capture_exact_window_png(175, run_command=run, system_name="Linux")
    assert calls == []


def test_capture_uses_only_exact_id_and_removes_secure_temp_artifact(tmp_path: Path) -> None:
    calls: list[list[str]] = []
    observed_modes: list[tuple[int, int]] = []

    def run(argv: list[str], **_kwargs):
        calls.append(list(argv))
        destination = Path(argv[-1])
        observed_modes.append(
            (
                destination.parent.stat().st_mode & 0o777,
                destination.stat().st_mode & 0o777,
            )
        )
        destination.write_bytes(b"\x89PNG\r\n\x1a\nexact-window")
        return _completed(argv)

    captured = capture_exact_window_png(
        175,
        run_command=run,
        temp_parent=tmp_path,
        system_name="Darwin",
    )

    assert captured == b"\x89PNG\r\n\x1a\nexact-window"
    assert calls == [["screencapture", "-x", "-l", "175", calls[0][-1]]]
    assert observed_modes == [(0o700, 0o600)]
    assert list(tmp_path.iterdir()) == []


def test_capture_surfaces_secure_temp_png_cleanup_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_rmtree = locator_module.shutil.rmtree

    def run(argv: list[str], **_kwargs):
        Path(argv[-1]).write_bytes(b"\x89PNG\r\n\x1a\nexact-window")
        return _completed(argv)

    def fail_cleanup(*_args, **_kwargs):
        raise OSError("permission denied")

    monkeypatch.setattr(locator_module.shutil, "rmtree", fail_cleanup)
    with pytest.raises(WindowResolutionError, match="temporary capture cleanup failed"):
        capture_exact_window_png(
            175,
            run_command=run,
            temp_parent=tmp_path,
            system_name="Darwin",
        )

    leftovers = list(tmp_path.iterdir())
    assert len(leftovers) == 1
    monkeypatch.setattr(locator_module.shutil, "rmtree", real_rmtree)
    real_rmtree(leftovers[0])


def test_bundled_swift_locator_emits_frontmost_layer_zero_proof() -> None:
    repo = Path(__file__).resolve().parents[1]
    source = (repo / "skills/login/scripts/macos_window_locator.swift").read_text()
    assert '"frontmost_layer0"' in source
    assert "frontmostLayerZeroWindowID" in source


@pytest.mark.skipif(os.uname().sysname != "Darwin", reason="CoreGraphics is macOS-only")
def test_bundled_swift_locator_typechecks_on_macos() -> None:
    repo = Path(__file__).resolve().parents[1]
    subprocess.run(
        ["swiftc", "-typecheck", str(repo / "skills/login/scripts/macos_window_locator.swift")],
        check=True,
    )
