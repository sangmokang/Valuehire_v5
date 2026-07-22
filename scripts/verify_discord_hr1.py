#!/usr/bin/env python3
"""Fail-closed verifier for the secret-free HR-1 live acceptance receipt."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

from tools.multi_position_sourcing.discord_hr1 import Hr1ReceiptError, validate_hr1_receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="verify Discord direct-gateway HR-1 receipt")
    parser.add_argument("receipt", type=Path)
    args = parser.parse_args(argv)
    verifier_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    try:
        payload = json.loads(args.receipt.read_text(encoding="utf-8"))
        validate_hr1_receipt(
            payload,
            expected_verifier_sha256=verifier_hash,
            forbidden_values=tuple(filter(None, (
                os.environ.get("DISCORD_BOT_TOKEN", ""),
                os.environ.get("SUPABASE_SERVICE_ROLE_KEY", ""),
            ))),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, Hr1ReceiptError) as exc:
        print(f"HR-1 RED: {exc}")
        return 1
    print(
        "HR-1 GREEN: isolated gateway lease/RPC/heartbeat/idempotency, "
        "Claude/Codex/natural-language done, requester replies=1, gateway stopped"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
