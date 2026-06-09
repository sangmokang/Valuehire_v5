from __future__ import annotations

import argparse
import json
import os
from typing import Any
from urllib import error, request

from .discord_routing import discord_slash_command_payloads


DISCORD_API_BASE = "https://discord.com/api/v10"
DISCORD_HTTP_ERROR_HINTS = {
    400: "discord_command_payload_rejected",
    401: "discord_bot_token_rejected",
    403: "discord_application_forbidden",
    404: "discord_application_or_guild_not_found",
    429: "discord_rate_limited",
}


def discord_command_registration_url(application_id: str, guild_id: str = "") -> str:
    if guild_id:
        return f"{DISCORD_API_BASE}/applications/{application_id}/guilds/{guild_id}/commands"
    return f"{DISCORD_API_BASE}/applications/{application_id}/commands"


def bulk_register_discord_commands(
    *,
    application_id: str,
    bot_token: str,
    guild_id: str = "",
    payloads: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    payload = payloads if payloads is not None else discord_slash_command_payloads()
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        discord_command_registration_url(application_id, guild_id),
        data=body,
        method="PUT",
        headers={
            "Authorization": f"Bot {bot_token}",
            "Content-Type": "application/json",
            "User-Agent": "Valuehire-Multisearch/1.0",
        },
    )
    try:
        with request.urlopen(req, timeout=30) as response:
            response_body = response.read().decode("utf-8")
            return {
                "ok": True,
                "status": response.status,
                "body": json.loads(response_body) if response_body else None,
            }
    except error.HTTPError as exc:
        exc.close()
        return {
            "ok": False,
            "status": exc.code,
            "error_type": "HTTPError",
            "error_hint": DISCORD_HTTP_ERROR_HINTS.get(exc.code, "discord_api_error"),
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="Register Valuehire Discord slash commands.")
    parser.add_argument("--application-id", default=os.environ.get("DISCORD_CLIENT_ID", ""))
    parser.add_argument("--guild-id", default=os.environ.get("DISCORD_GUILD_ID", ""))
    parser.add_argument("--apply", action="store_true", help="Actually call Discord. Default prints a dry-run payload.")
    args = parser.parse_args()

    if not args.application_id:
        raise SystemExit("DISCORD_CLIENT_ID or --application-id is required")

    payloads = discord_slash_command_payloads()
    if not args.apply:
        print(
            json.dumps(
                {
                    "dry_run": True,
                    "url": discord_command_registration_url(args.application_id, args.guild_id),
                    "commands": payloads,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    token = os.environ.get("DISCORD_BOT_TOKEN", "")
    if not token:
        raise SystemExit("DISCORD_BOT_TOKEN is required when --apply is set")

    result = bulk_register_discord_commands(
        application_id=args.application_id,
        bot_token=token,
        guild_id=args.guild_id,
        payloads=payloads,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
