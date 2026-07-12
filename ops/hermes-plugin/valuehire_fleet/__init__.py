"""Valuehire fleet plugin for the Hermes gateway (~/.hermes/hermes-agent).

Wires fleet-run/fleet-status/fleet-resume/fleet-cancel slash commands to the
canonical dispatcher in tools/multi_position_sourcing/hermes_fleet_bridge.py
(Valuehire_v5 repo) — this plugin never re-implements auth/queue logic.

Deploy: symlink this directory to ``~/.hermes/plugins/valuehire_fleet`` so the
installed plugin is always exactly the git-tracked source (no stale-copy
drift), then add ``valuehire_fleet`` to ``plugins.enabled`` in
``~/.hermes/config.yaml`` and restart the gateway. See
docs/prompts/fleet-control-hermes-bridge-prompts-2026-07-13.md for the full
install/rollback procedure — do not do this without owner approval (touches
the live production Discord bot).

Identity problem (structural Hermes limitation): register_command() handlers
only receive ``raw_args: str``, never the sender's platform user id
(hermes_cli/plugins.py:414). We solve this with the ``pre_gateway_dispatch``
hook, which fires once per incoming message BEFORE command dispatch and DOES
receive the full ``MessageEvent`` (event.source.user_id, event.source.platform
— gateway/session.py:SessionSource). We stash the sender id in a contextvar
there; the command handlers read it back. If the hook never fires for some
reason, the contextvar stays at its default "" and
``hermes_fleet_bridge.dispatch_hermes_fleet_command()`` fail-closes (raises)
rather than assuming owner or member identity.
"""

from __future__ import annotations

import contextvars
import json
import sys
from pathlib import Path

# Resolve the Valuehire_v5 repo root through this file's own path. Works
# whether this file is reached via the ~/.hermes/plugins/valuehire_fleet
# symlink or the repo path directly — Path.resolve() follows symlinks.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_GATEWAY_USER_ID: "contextvars.ContextVar[str]" = contextvars.ContextVar(
    "valuehire_fleet_gateway_user_id", default=""
)

# Only Discord identities are meaningful here — docs/search-access.md only
# lists Discord snowflake IDs. A Telegram/WhatsApp numeric id must never be
# silently treated as a Discord id (cross-platform identity conflation).
_TRUSTED_PLATFORM = "discord"


def _platform_name(source: object) -> str:
    platform = getattr(source, "platform", None)
    if platform is None:
        return ""
    value = getattr(platform, "value", platform)
    return str(value).strip().lower()


def _capture_gateway_identity(event=None, gateway=None, session_store=None, **_kwargs):
    """``pre_gateway_dispatch`` hook — runs before command dispatch, has the event."""
    user_id = ""
    source = getattr(event, "source", None)
    if source is not None and _platform_name(source) == _TRUSTED_PLATFORM:
        raw = getattr(source, "user_id", None)
        if raw:
            user_id = str(raw).strip()
    _GATEWAY_USER_ID.set(user_id)
    return None  # None == {"action": "allow"} — never rewrite/skip the message here


def _make_handler(command_name: str):
    def _handler(raw_args: str) -> str:
        from tools.multi_position_sourcing.hermes_fleet_bridge import (
            HermesFleetBridgeError,
            dispatch_hermes_fleet_command,
        )

        gateway_user_id = _GATEWAY_USER_ID.get()
        try:
            result = dispatch_hermes_fleet_command(
                command_name, raw_args, gateway_user_id=gateway_user_id
            )
        except HermesFleetBridgeError as exc:
            return f"거부됨: {exc}"
        return json.dumps(result, ensure_ascii=False)

    return _handler


_COMMANDS: tuple[tuple[str, str, str], ...] = (
    ("fleet-run",
     "skill:<humansearch|aisearch|url> url:<position URL> machine:<macmini|macbook|winpc>",
     "Queue a Valuehire fleet search job."),
    ("fleet-status", "", "Show recent Valuehire fleet jobs."),
    ("fleet-resume", "job:<id>", "(owner) Resume a paused fleet job."),
    ("fleet-cancel", "job:<id>", "(owner) Cancel a queued/paused fleet job."),
)


def register(ctx) -> None:
    ctx.register_hook("pre_gateway_dispatch", _capture_gateway_identity)
    for name, args_hint, description in _COMMANDS:
        ctx.register_command(
            name, handler=_make_handler(name), description=description, args_hint=args_hint
        )
