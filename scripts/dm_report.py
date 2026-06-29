#!/usr/bin/env python3
"""사장님 디스코드 DM 보고용 헬퍼.
사용: python3 scripts/dm_report.py "<메시지>"
DISCORD_BOT_TOKEN(.env.local)으로 user 814353841088757800에게 DM 채널 열고 전송.
"""
import os
import sys
import json
import urllib.request
import urllib.error

RECIPIENT_ID = "814353841088757800"


def _load_token() -> str:
    tok = os.environ.get("DISCORD_BOT_TOKEN")
    if tok:
        return tok.strip()
    for path in (".env.local", ".env"):
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line.startswith("DISCORD_BOT_TOKEN="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("DISCORD_BOT_TOKEN not found")


def _api(method: str, path: str, token: str, payload: dict | None = None) -> dict:
    import time
    url = f"https://discord.com/api/v10{path}"
    data = json.dumps(payload).encode() if payload is not None else None
    for attempt in range(6):
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", f"Bot {token}")
        req.add_header("Content-Type", "application/json")
        req.add_header("User-Agent", "ValuehireDM/1.0")
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                body = resp.read().decode()
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as e:
            if e.code == 429:
                retry_after = 1.5
                try:
                    retry_after = float(json.loads(e.read().decode()).get("retry_after", 1.5))
                except Exception:
                    pass
                time.sleep(min(retry_after + 0.3, 5))
                continue
            raise
    raise SystemExit("discord api rate-limited after retries")


def send_dm(message: str) -> None:
    token = _load_token()
    dm = _api("POST", "/users/@me/channels", token, {"recipient_id": RECIPIENT_ID})
    channel_id = dm["id"]
    _api("POST", f"/channels/{channel_id}/messages", token, {"content": message})


if __name__ == "__main__":
    msg = sys.argv[1] if len(sys.argv) > 1 else "(empty)"
    send_dm(msg)
    print("sent")
