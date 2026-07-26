from __future__ import annotations

import pytest

from tools.multi_position_sourcing.fleet_args import FleetArgsError, parse_fleet_args


@pytest.mark.parametrize(
    ("alias", "canonical"),
    [
        ("macbook_pro", "macbook"),
        ("win", "winpc"),
        ("windows", "winpc"),
        ("윈도우", "winpc"),
        ("윈도우pc", "winpc"),
        ("맥미니", "macmini"),
        ("mini", "macmini"),
        ("맥북", "macbook"),
    ],
)
def test_external_machine_aliases_are_canonicalized(alias: str, canonical: str) -> None:
    parsed = parse_fleet_args(
        "fleet-run",
        f"skill:humansearch url:https://app.clickup.com/t/abc machine:{alias}",
    )
    assert parsed["machine"] == canonical


def test_bare_legacy_machine_alias_is_canonicalized() -> None:
    parsed = parse_fleet_args(
        "fleet-run",
        "humansearch https://app.clickup.com/t/abc macbook_pro",
    )
    assert parsed["machine"] == "macbook"


@pytest.mark.parametrize(
    "raw_args",
    [
        "skill:humansearch url:https://app.clickup.com/t/abc machine:MACBOOK",
        "skill:humansearch url:https://app.clickup.com/t/abc machine:WINDOWS",
        'skill:humansearch url:https://app.clickup.com/t/abc machine:" macbook"',
        'skill:humansearch url:https://app.clickup.com/t/abc machine:"macbook "',
    ],
)
def test_machine_values_reject_case_and_whitespace_variants(raw_args: str) -> None:
    with pytest.raises(FleetArgsError):
        parse_fleet_args("fleet-run", raw_args)

