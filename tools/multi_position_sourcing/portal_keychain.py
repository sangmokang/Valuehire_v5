from __future__ import annotations

import subprocess


def add_generic_password(*, service: str, account: str, password: str) -> subprocess.CompletedProcess[bytes]:
    """Write a generic password without placing the secret in process arguments."""
    return subprocess.run(
        [
            "security",
            "add-generic-password",
            "-U",
            "-s",
            service,
            "-a",
            account,
            "-w",
        ],
        input=(password + "\n").encode("utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
