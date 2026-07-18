"""Resolve and capture one exact macOS browser window for a CDP target.

The CoreGraphics bridge is intentionally a bundled Swift script.  Importing this
module therefore remains safe on Linux CI and on macOS Python installations that
do not provide the optional ``Quartz`` bindings.
"""
from __future__ import annotations

import json
import math
import platform
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any


RunCommand = Callable[..., subprocess.CompletedProcess[str]]
DEFAULT_BOUNDS_TOLERANCE = 2.0
DEFAULT_COMMAND_TIMEOUT_SECONDS = 15


class WindowResolutionError(RuntimeError):
    """The requested CDP target could not be mapped to one exact OS window."""


@dataclass(frozen=True)
class WindowBounds:
    left: float
    top: float
    width: float
    height: float

    def __post_init__(self) -> None:
        values = (self.left, self.top, self.width, self.height)
        if (
            any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in values)
            or not all(math.isfinite(float(value)) for value in values)
            or self.width <= 0
            or self.height <= 0
        ):
            raise ValueError("window bounds must be finite numbers with positive size")

    def matches(self, other: "WindowBounds", *, tolerance: float) -> bool:
        return all(
            abs(float(left) - float(right)) <= tolerance
            for left, right in zip(
                (self.left, self.top, self.width, self.height),
                (other.left, other.top, other.width, other.height),
                strict=True,
            )
        )


@dataclass(frozen=True)
class CdpWindowIdentity:
    browser_pid: int
    target_id: str
    title_marker: str
    bounds: WindowBounds

    def __post_init__(self) -> None:
        if isinstance(self.browser_pid, bool) or not isinstance(self.browser_pid, int) or self.browser_pid <= 0:
            raise ValueError("browser_pid must be a positive integer")
        if not isinstance(self.target_id, str) or not self.target_id.strip():
            raise ValueError("target_id must be non-empty")
        if not isinstance(self.title_marker, str):
            raise ValueError("title_marker must be a string")


@dataclass(frozen=True)
class MacWindowRef:
    cg_window_id: int
    owner_pid: int
    title: str
    bounds: WindowBounds
    on_screen: bool
    frontmost_layer0: bool


def _default_swift_script() -> Path:
    return Path(__file__).resolve().parents[2] / "skills" / "login" / "scripts" / "macos_window_locator.swift"


def _number_arg(value: float) -> str:
    numeric = float(value)
    if numeric.is_integer():
        return str(int(numeric))
    return format(numeric, ".15g")


def _payload_window(value: Any) -> MacWindowRef | None:
    if not isinstance(value, dict):
        return None
    window_id = value.get("cg_window_id")
    owner_pid = value.get("owner_pid")
    layer = value.get("layer")
    title = value.get("title")
    on_screen = value.get("on_screen")
    frontmost_layer0 = value.get("frontmost_layer0")
    raw_bounds = value.get("bounds")
    if (
        isinstance(window_id, bool)
        or not isinstance(window_id, int)
        or window_id <= 0
        or isinstance(owner_pid, bool)
        or not isinstance(owner_pid, int)
        or owner_pid <= 0
        or isinstance(layer, bool)
        or not isinstance(layer, int)
        or layer != 0
        or not isinstance(title, str)
        or not isinstance(on_screen, bool)
        or not isinstance(frontmost_layer0, bool)
        or not isinstance(raw_bounds, dict)
    ):
        return None
    try:
        bounds = WindowBounds(
            left=raw_bounds["left"],
            top=raw_bounds["top"],
            width=raw_bounds["width"],
            height=raw_bounds["height"],
        )
    except (KeyError, TypeError, ValueError):
        return None
    return MacWindowRef(
        cg_window_id=window_id,
        owner_pid=owner_pid,
        title=title,
        bounds=bounds,
        on_screen=on_screen,
        frontmost_layer0=frontmost_layer0,
    )


def resolve_exact_macos_window(
    identity: CdpWindowIdentity,
    *,
    run_command: RunCommand = subprocess.run,
    system_name: str | None = None,
    swift_script: Path | None = None,
    bounds_tolerance: float = DEFAULT_BOUNDS_TOLERANCE,
    require_on_screen: bool = True,
    require_frontmost: bool = False,
) -> MacWindowRef:
    """Map a browser PID + CDP bounds + non-secret title marker to one CGWindow.

    Swift filters the OS list first; this function independently validates its
    JSON output.  It deliberately has no title-only or first-window fallback.
    """

    system = system_name or platform.system()
    if system != "Darwin":
        raise WindowResolutionError(f"exact macOS window resolution unavailable on {system or 'unknown'}")
    if not math.isfinite(bounds_tolerance) or bounds_tolerance < 0:
        raise WindowResolutionError("invalid window bounds tolerance")
    if not isinstance(require_on_screen, bool):
        raise WindowResolutionError("require_on_screen must be boolean")
    if not isinstance(require_frontmost, bool):
        raise WindowResolutionError("require_frontmost must be boolean")
    script = Path(swift_script) if swift_script is not None else _default_swift_script()
    if not script.is_file() or script.stat().st_size <= 0:
        raise WindowResolutionError("bundled Swift window locator is missing")

    argv = [
        "swift",
        str(script),
        "--pid",
        str(identity.browser_pid),
        "--marker",
        identity.title_marker,
        "--left",
        _number_arg(identity.bounds.left),
        "--top",
        _number_arg(identity.bounds.top),
        "--width",
        _number_arg(identity.bounds.width),
        "--height",
        _number_arg(identity.bounds.height),
        "--tolerance",
        _number_arg(bounds_tolerance),
        "--require-on-screen",
        "true" if require_on_screen else "false",
    ]
    try:
        result = run_command(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=DEFAULT_COMMAND_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        raise WindowResolutionError("Swift window locator could not run") from exc
    if result.returncode != 0:
        raise WindowResolutionError("Swift window locator failed")
    try:
        payload = json.loads(result.stdout or "")
    except (json.JSONDecodeError, TypeError) as exc:
        raise WindowResolutionError("Swift window locator returned invalid JSON") from exc
    if not isinstance(payload, list):
        raise WindowResolutionError("Swift window locator result must be a list")

    matches: list[MacWindowRef] = []
    for item in payload:
        candidate = _payload_window(item)
        if candidate is None:
            continue
        if candidate.owner_pid != identity.browser_pid:
            continue
        if require_on_screen and candidate.on_screen is not True:
            continue
        if require_frontmost and candidate.frontmost_layer0 is not True:
            continue
        if identity.title_marker and not candidate.title.startswith(identity.title_marker):
            continue
        if not identity.bounds.matches(candidate.bounds, tolerance=bounds_tolerance):
            continue
        matches.append(candidate)
    if len(matches) != 1:
        raise WindowResolutionError(f"exact window match count was {len(matches)}")
    return matches[0]


def activate_exact_macos_application(
    browser_pid: int,
    *,
    run_command: RunCommand = subprocess.run,
    system_name: str | None = None,
    swift_script: Path | None = None,
) -> bool:
    """Activate only the root browser process already bound to the exact target."""
    system = system_name or platform.system()
    if system != "Darwin":
        raise WindowResolutionError(f"exact macOS app activation unavailable on {system or 'unknown'}")
    if isinstance(browser_pid, bool) or not isinstance(browser_pid, int) or browser_pid <= 0:
        raise WindowResolutionError("browser PID must be a positive integer")
    script = Path(swift_script) if swift_script is not None else _default_swift_script()
    if not script.is_file() or script.stat().st_size <= 0:
        raise WindowResolutionError("bundled Swift window locator is missing")
    argv = ["swift", str(script), "--activate-pid", str(browser_pid)]
    try:
        result = run_command(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=DEFAULT_COMMAND_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        raise WindowResolutionError("exact browser application activation could not run") from exc
    if result.returncode != 0:
        raise WindowResolutionError("exact browser application activation failed")
    try:
        payload = json.loads(result.stdout or "")
    except (json.JSONDecodeError, TypeError) as exc:
        raise WindowResolutionError("exact browser application activation returned invalid JSON") from exc
    if not isinstance(payload, dict) or payload != {"activated": True, "pid": browser_pid}:
        raise WindowResolutionError("exact browser application activation was not proven")
    return True


def capture_exact_window_png(
    cg_window_id: int,
    *,
    run_command: RunCommand = subprocess.run,
    temp_parent: Path | None = None,
    system_name: str | None = None,
) -> bytes:
    """Capture exactly one CGWindow and remove the secure temporary artifact."""

    system = system_name or platform.system()
    if system != "Darwin":
        raise WindowResolutionError(f"exact macOS window capture unavailable on {system or 'unknown'}")
    if isinstance(cg_window_id, bool) or not isinstance(cg_window_id, int) or cg_window_id <= 0:
        raise WindowResolutionError("CGWindowID must be a positive integer")

    parent = None if temp_parent is None else str(Path(temp_parent))
    temp_dir = Path(tempfile.mkdtemp(prefix="valuehire-login-window-", dir=parent))
    destination = temp_dir / "window.png"
    try:
        temp_dir.chmod(0o700)
        destination.touch(mode=0o600, exist_ok=False)
        destination.chmod(0o600)
        argv = ["screencapture", "-x", "-l", str(cg_window_id), str(destination)]
        try:
            result = run_command(
                argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=DEFAULT_COMMAND_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            raise WindowResolutionError("exact window capture could not run") from exc
        if result.returncode != 0:
            raise WindowResolutionError("exact window capture failed")
        data = destination.read_bytes()
        if not data.startswith(b"\x89PNG\r\n\x1a\n"):
            raise WindowResolutionError("exact window capture was not a PNG")
        return data
    except OSError as exc:
        raise WindowResolutionError("secure exact-window capture failed") from exc
    finally:
        try:
            shutil.rmtree(temp_dir)
        except Exception as exc:
            raise WindowResolutionError("secure temporary capture cleanup failed") from exc
