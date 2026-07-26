from __future__ import annotations

import pytest

from tools.multi_position_sourcing.browser_inventory import collect_browser_inventory


READY = {"registered": True, "online": True, "reason": None}


def _collect(
    processes: str,
    *,
    listeners: list[dict] | None = None,
    responses: dict | None = None,
):
    return collect_browser_inventory(
        local_machine_id="macmini",
        machine_readiness=READY,
        process_snapshot=processes,
        listener_snapshot=listeners or [],
        endpoint_responses=responses or {},
    )


def _root(pid: int, profile: str, port: str = "9225") -> str:
    return (
        f"{pid} /Applications/Google Chrome.app/Contents/MacOS/Google Chrome "
        f"--remote-debugging-port={port} --user-data-dir={profile} --no-first-run"
    )


def test_collects_multiple_roots_and_spaced_profile_until_next_long_option():
    report = _collect(
        "\n".join(
            [
                _root(101, '"/tmp/Quoted Profile"', "9223"),
                _root(202, "/tmp/Plain Spaced Profile", "9224"),
                _root(203, "/tmp/Plain Spaced Profile", "9224")
                + " --type=renderer",
            ]
        ),
        listeners=[
            {"pid": 101, "address": "127.0.0.1", "port": 9223},
            {"pid": 202, "address": "127.0.0.1", "port": 9224},
        ],
    )

    assert [(item["browser_pid"], item["profile_path"]) for item in report] == [
        (101, "/tmp/Quoted Profile"),
        (202, "/tmp/Plain Spaced Profile"),
    ]
    assert all(item["issues"] == [] for item in report)


def test_listener_mismatch_dead_endpoint_and_ambiguous_port_are_explicit():
    report = _collect(
        "\n".join(
            [
                _root(101, "/tmp/A", "9223"),
                _root(202, "/tmp/B", "9224")
                .replace(
                    "--remote-debugging-port=9224",
                    "--remote-debugging-port=9224 --remote-debugging-port=9334",
                ),
            ]
        ),
        listeners=[{"pid": 999, "address": "127.0.0.1", "port": 9223}],
    )

    assert report[0]["listen_pid"] == 999
    assert report[0]["endpoint_live"] is False
    assert report[0]["issues"] == [
        "LISTENER_PID_MISMATCH",
        "ENDPOINT_DEAD",
    ]
    assert report[1]["declared_port"] is None
    assert report[1]["endpoint"] is None
    assert report[1]["issues"] == ["AMBIGUOUS_DECLARED_PORT"]


def test_remote_debugging_address_and_remote_listener_never_become_endpoint():
    process = _root(101, "/tmp/A", "9223").replace(
        "--user-data-dir", "--remote-debugging-address=0.0.0.0 --user-data-dir"
    )
    report = _collect(
        process,
        listeners=[{"pid": 101, "address": "0.0.0.0", "port": 9223}],
        responses={
            "http://10.0.0.9:9223": {
                "version": {"Browser": "Chrome"},
                "targets": [],
            }
        },
    )

    assert report[0]["endpoint"] is None
    assert report[0]["endpoint_live"] is False
    assert report[0]["issues"] == [
        "NON_LOOPBACK_DEBUG_ADDRESS",
        "NON_LOOPBACK_LISTENER",
    ]


def test_duplicate_profile_and_duplicate_listener_are_explicit():
    report = _collect(
        "\n".join([_root(101, "/tmp/shared", "9223"), _root(202, "/tmp/shared", "9224")]),
        listeners=[
            {"pid": 101, "address": "127.0.0.1", "port": 9223},
            {"pid": 102, "address": "127.0.0.1", "port": 9223},
            {"pid": 202, "address": "127.0.0.1", "port": 9224},
        ],
    )

    assert report[0]["listen_pid"] is None
    assert "AMBIGUOUS_LISTENER" in report[0]["issues"]
    assert all("DUPLICATE_PROFILE" in item["issues"] for item in report)


def test_live_endpoint_collects_sanitized_targets_without_secrets():
    process = _root(101, "/tmp/A", "9223")
    report = _collect(
        process,
        listeners=[{"pid": 101, "address": "127.0.0.1", "port": 9223}],
        responses={
            "http://127.0.0.1:9223": {
                "version": {"Browser": "Chrome/140"},
                "targets": [
                    {
                        "id": "page-1",
                        "type": "page",
                        "url": "https://www.linkedin.com/talent/home?token=secret#private",
                        "marker_names": ["authenticated_shell", "", 7],
                        "webSocketDebuggerUrl": "ws://secret",
                    },
                    {
                        "id": "worker-1",
                        "type": "service_worker",
                        "url": "chrome-extension://abc/background.html?key=secret",
                    },
                ],
            }
        },
    )

    assert report[0]["endpoint_live"] is True
    assert report[0]["targets"] == [
        {
            "target_id": "page-1",
            "type": "page",
            "sanitized_url": "https://www.linkedin.com/talent/home",
            "site": "linkedin_rps",
            "marker_names": ["authenticated_shell"],
        },
        {
            "target_id": "worker-1",
            "type": "service_worker",
            "sanitized_url": "chrome-extension://abc/background.html",
            "site": None,
            "marker_names": [],
        },
    ]
    assert "secret" not in repr(report)


@pytest.mark.parametrize(
    ("machine_id", "readiness"),
    [
        ("ghost", READY),
        ("macbook", READY),
        ("macmini", {"registered": True, "online": False, "reason": "STALE_HEARTBEAT"}),
    ],
)
def test_invalid_local_machine_readiness_fails_closed(machine_id, readiness):
    with pytest.raises(ValueError, match="machine readiness"):
        collect_browser_inventory(
            local_machine_id=machine_id,
            machine_readiness=readiness,
            process_snapshot="",
            listener_snapshot=[],
            endpoint_responses={},
        )
