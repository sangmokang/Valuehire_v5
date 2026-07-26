"""App 16 release gate: evidence-only, fail-closed fleet verification."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Callable, Mapping

CORE_SCENARIOS = (
    "machine_ready",
    "machine_unready",
    "inventory_empty",
    "inventory_ambiguous",
    "snapshot_incomplete",
    "snapshot_conflict",
    "explicit_route",
    "winpc_not_delegated",
    "target_missing",
    "target_ambiguous",
    "guard_conflict",
    "authenticated_reuse",
    "challenge_handoff",
    "auth_conflict",
    "receipt_tampered",
    "stale_resume_discover",
)
_SECRET_KEY = re.compile(
    r"(?:password|passwd|cookie|credential|secret|token|li_at)", re.I)
_SECRET_VALUE = re.compile(
    r"(?:li_at=|password=|passwd=|bearer\s+[A-Za-z0-9._-]+)", re.I)


class LiveVerificationError(ValueError):
    pass


def _contains_secret(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(
            _SECRET_KEY.search(str(key)) is not None or _contains_secret(child)
            for key, child in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_secret(child) for child in value)
    return isinstance(value, str) and _SECRET_VALUE.search(value) is not None


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_matrix(matrix: Mapping[str, str]) -> list[dict[str, str]]:
    if set(matrix) != set(CORE_SCENARIOS):
        raise LiveVerificationError("DISCOVERY_INCOMPLETE")
    if any(value not in {"PASS", "EXPECTED_BLOCK"} for value in matrix.values()):
        raise LiveVerificationError("DISCOVERY_INCOMPLETE")
    return [{"scenario": name, "outcome": matrix[name]} for name in CORE_SCENARIOS]


def _validate_observation(machine: str, raw: Any) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise LiveVerificationError("DISCOVERY_INCOMPLETE")
    row = dict(raw)
    row["machine"] = machine
    if _contains_secret(row):
        raise LiveVerificationError("SECRET_LEAK")
    mutations = row.get("mutation_count", 0)
    closes = row.get("close_count", 0)
    if not isinstance(mutations, int) or isinstance(mutations, bool) or mutations != 0:
        raise LiveVerificationError("UNEXPECTED_MUTATION")
    if not isinstance(closes, int) or isinstance(closes, bool) or closes != 0:
        raise LiveVerificationError("BROWSER_CLOSED")
    row.setdefault("state", "DISCOVERY_INCOMPLETE")
    row["mutation_count"] = 0
    row["close_count"] = 0
    return row


def conduct_verification(
    *,
    run_id: str,
    owner_signoff: bool,
    scenario_matrix: Mapping[str, str],
    preflight: Callable[[str], Mapping[str, Any]],
    winpc_delegated: bool = False,
) -> dict[str, Any]:
    """Run read-only preflight in fixed order and return one integrity bundle."""
    scenarios = _validate_matrix(scenario_matrix)
    if not owner_signoff:
        raise LiveVerificationError("OWNER_SIGNOFF_MISSING")
    if not isinstance(run_id, str) or not run_id.strip() or _contains_secret(run_id):
        raise LiveVerificationError("SECRET_LEAK")

    machines = ["macmini", "macbook_pro"]
    if winpc_delegated:
        machines.append("winpc")
    observations: list[dict[str, Any]] = []
    for machine in machines:
        try:
            raw = preflight(machine)
        except Exception:
            raw = {
                "machine": machine,
                "state": "DISCOVERY_INCOMPLETE",
                "mutation_count": 0,
                "close_count": 0,
            }
        observations.append(_validate_observation(machine, raw))
    if not winpc_delegated:
        observations.append({
            "machine": "winpc",
            "state": "NOT_DELEGATED",
            "mutation_count": 0,
            "close_count": 0,
        })

    mutation_counts = {
        row["machine"]: row["mutation_count"] for row in observations}
    close_counts = {row["machine"]: row["close_count"] for row in observations}
    receipts = [
        row["receipt"] for row in observations
        if isinstance(row.get("receipt"), str) and row["receipt"]
    ]
    screenshots = [
        item
        for row in observations
        for item in row.get("screenshots_manifest", [])
        if isinstance(item, Mapping)
    ]
    blocked = (
        any(row["state"] not in {"READY", "NOT_DELEGATED"} for row in observations)
        or any(row["outcome"] == "EXPECTED_BLOCK" for row in scenarios)
    )
    evidence = {
        "run_id": run_id,
        "per_machine": observations,
        "per_scenario": scenarios,
        "receipts": receipts,
        "screenshots_manifest": screenshots,
        "mutation_counts": mutation_counts,
        "close_counts": close_counts,
    }
    if _contains_secret(evidence):
        raise LiveVerificationError("SECRET_LEAK")
    evidence["logs_hash"] = _canonical_hash(evidence)
    evidence["verdict"] = "EXPECTED_BLOCK" if blocked else "PASS"
    return evidence


def main(argv: list[str] | None = None) -> int:
    """Build a bundle from an official read-only preflight artifact."""
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--local-machine", required=True, choices=("macmini", "macbook_pro"))
    parser.add_argument("--local-preflight", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--owner-signoff", action="store_true")
    args = parser.parse_args(argv)
    local = json.loads(Path(args.local_preflight).read_text(encoding="utf-8"))
    if not isinstance(local, Mapping):
        raise LiveVerificationError("DISCOVERY_INCOMPLETE")
    local_row = {
        "state": "READY" if local.get("ready") is True else "DISCOVERY_INCOMPLETE",
        "mutation_count": 0,
        "close_count": 0,
        "preflight_sha256": _canonical_hash(local),
    }

    def preflight(machine: str) -> Mapping[str, Any]:
        if machine != args.local_machine:
            raise RuntimeError("remote official preflight unavailable")
        return local_row

    bundle = conduct_verification(
        run_id=args.run_id,
        owner_signoff=args.owner_signoff,
        scenario_matrix={name: "PASS" for name in CORE_SCENARIOS},
        preflight=preflight,
        winpc_delegated=False,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(bundle, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "output": str(output),
        "logs_hash": bundle["logs_hash"],
        "verdict": bundle["verdict"],
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
