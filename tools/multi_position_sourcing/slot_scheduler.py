"""Pure, deterministic browser-slot dispatch planning.

This module performs no I/O and owns no database or browser state.  It models the
safety boundary for issue #125: one mutating slot per machine, one job per slot,
requester fairness, capability matching, and account capacity.  Later database
work must enforce the same decisions atomically with leases and fencing.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import math
from typing import Mapping, Sequence

__all__ = [
    "Dispatch",
    "Job",
    "RequesterState",
    "Slot",
    "plan_dispatches",
]

_READY_STATE = "ready"
_KNOWN_SLOT_STATES = frozenset(
    {
        "ready",
        "busy",
        "parked",
        "human_active",
        "challenge",
        "degraded",
        "offline",
        "draining",
    }
)


@dataclass(frozen=True)
class Job:
    requester_id: str
    job_id: int
    created_at: int | float
    resource_class: str
    requirements: Mapping[str, object]
    requested_machine: str | None
    account_key: str


@dataclass(frozen=True)
class Slot:
    slot_id: str
    machine_id: str
    resource_class: str
    capabilities: Mapping[str, object]
    account_key: str
    state: str
    fresh: bool


@dataclass(frozen=True)
class RequesterState:
    active_count: int
    last_dispatch_seq: int


@dataclass(frozen=True)
class Dispatch:
    requester_id: str
    job_id: int
    slot_id: str
    machine_id: str
    account_key: str
    dispatch_seq: int


def _nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip()) and value == value.strip()


def _plain_int(value: object, *, minimum: int = 0) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= minimum


def _valid_created_at(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
    )


def _valid_json_value(value: object, seen: set[int] | None = None) -> bool:
    """Accept only finite JSON-shaped values; reject cycles and opaque objects."""
    if value is None or isinstance(value, (str, bool)):
        return True
    if isinstance(value, int):
        return not isinstance(value, bool)
    if isinstance(value, float):
        return math.isfinite(value)
    if not isinstance(value, (Mapping, list)):
        return False
    visited = set() if seen is None else seen
    identity = id(value)
    if identity in visited:
        return False
    visited.add(identity)
    try:
        if isinstance(value, Mapping):
            return all(
                _nonempty(key) and _valid_json_value(item, visited)
                for key, item in value.items()
            )
        return all(_valid_json_value(item, visited) for item in value)
    finally:
        visited.remove(identity)


def _valid_mapping(value: object) -> bool:
    return isinstance(value, Mapping) and _valid_json_value(value)


def _capability_equal(actual: object, expected: object) -> bool:
    """JSON types are exact: in particular, boolean True is not numeric 1."""
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, Mapping):
        return (
            set(actual) == set(expected)  # type: ignore[arg-type]
            and all(_capability_equal(actual[key], value) for key, value in expected.items())  # type: ignore[index]
        )
    if isinstance(expected, list):
        return len(actual) == len(expected) and all(  # type: ignore[arg-type]
            _capability_equal(left, right) for left, right in zip(actual, expected)  # type: ignore[arg-type]
        )
    return actual == expected


def _validate_inputs(
    jobs: Sequence[Job],
    slots: Sequence[Slot],
    requester_states: Mapping[str, RequesterState],
    account_capacities: Mapping[str, int],
    account_running: Mapping[str, int],
    *,
    next_dispatch_seq: int | None,
    max_dispatches: int | None,
) -> None:
    job_ids: set[int] = set()
    for candidate in jobs:
        if not isinstance(candidate, Job):
            raise ValueError("jobs must contain Job values")
        if not _nonempty(candidate.requester_id):
            raise ValueError("requester_id must be a non-empty normalized string")
        if not _plain_int(candidate.job_id, minimum=1):
            raise ValueError("job_id must be a positive integer")
        if candidate.job_id in job_ids:
            raise ValueError("duplicate job_id")
        job_ids.add(candidate.job_id)
        if not _valid_created_at(candidate.created_at):
            raise ValueError("created_at must be a finite non-negative number")
        if not _nonempty(candidate.resource_class):
            raise ValueError("resource_class must be a non-empty normalized string")
        if not _valid_mapping(candidate.requirements):
            raise ValueError("requirements must have normalized string keys")
        if candidate.requested_machine is not None and not _nonempty(candidate.requested_machine):
            raise ValueError("requested_machine must be None or a normalized string")
        if not _nonempty(candidate.account_key):
            raise ValueError("account_key must be a non-empty normalized string")

    slot_ids: set[str] = set()
    for candidate in slots:
        if not isinstance(candidate, Slot):
            raise ValueError("slots must contain Slot values")
        if not _nonempty(candidate.slot_id) or not _nonempty(candidate.machine_id):
            raise ValueError("slot_id and machine_id must be normalized strings")
        if candidate.slot_id in slot_ids:
            raise ValueError("duplicate slot_id")
        slot_ids.add(candidate.slot_id)
        if not _nonempty(candidate.resource_class) or not _nonempty(candidate.account_key):
            raise ValueError("slot resource_class and account_key must be normalized strings")
        if not _valid_mapping(candidate.capabilities):
            raise ValueError("capabilities must have normalized string keys")
        if candidate.state not in _KNOWN_SLOT_STATES:
            raise ValueError("unknown slot state")
        if not isinstance(candidate.fresh, bool):
            raise ValueError("fresh must be boolean")

    if not isinstance(requester_states, Mapping):
        raise ValueError("requester_states must be a mapping")
    for requester_id, state in requester_states.items():
        if not _nonempty(requester_id) or not isinstance(state, RequesterState):
            raise ValueError("invalid requester state")
        if not _plain_int(state.active_count) or not _plain_int(state.last_dispatch_seq):
            raise ValueError("requester counters must be non-negative integers")

    if not isinstance(account_capacities, Mapping) or not isinstance(account_running, Mapping):
        raise ValueError("account capacities and running counts must be mappings")
    for account_key, capacity in account_capacities.items():
        if not _nonempty(account_key) or not _plain_int(capacity, minimum=1):
            raise ValueError("account capacities must be positive integers")
        if account_key == "portal:linkedin_rps" and capacity != 1:
            raise ValueError("portal:linkedin_rps capacity is fixed at one")
    for account_key, running in account_running.items():
        if account_key not in account_capacities:
            raise ValueError("running count has no account capacity")
        if not _plain_int(running) or running > account_capacities[account_key]:
            raise ValueError("invalid account running count")

    if next_dispatch_seq is not None:
        if not _plain_int(next_dispatch_seq, minimum=1):
            raise ValueError("next_dispatch_seq must be a positive integer")
        highest_sequence = max(
            (state.last_dispatch_seq for state in requester_states.values()), default=0)
        if next_dispatch_seq <= highest_sequence:
            raise ValueError("next_dispatch_seq must advance all requester state")
    if max_dispatches is not None and not _plain_int(max_dispatches):
        raise ValueError("max_dispatches must be a non-negative integer")


def _slot_matches(candidate: Slot, queued: Job) -> bool:
    if candidate.state != _READY_STATE or not candidate.fresh:
        return False
    if candidate.resource_class != queued.resource_class:
        return False
    if candidate.account_key != queued.account_key:
        return False
    if queued.requested_machine is not None and candidate.machine_id != queued.requested_machine:
        return False
    return all(
        key in candidate.capabilities
        and _capability_equal(candidate.capabilities[key], expected)
        for key, expected in queued.requirements.items()
    )


def _future_dispatch_capacity(
    jobs: Sequence[Job],
    slots: Sequence[Slot],
    *,
    requester_states: Mapping[str, RequesterState],
    account_capacities: Mapping[str, int],
    account_counts: Mapping[str, int],
    excluded_machines: set[str],
) -> int:
    """Maximum remaining account→job→machine flow for a candidate choice."""
    slots_by_machine: dict[str, list[Slot]] = {}
    for candidate in slots:
        if candidate.machine_id not in excluded_machines and candidate.state == _READY_STATE and candidate.fresh:
            slots_by_machine.setdefault(candidate.machine_id, []).append(candidate)

    source: tuple[object, ...] = ("source",)
    sink: tuple[object, ...] = ("sink",)
    residual: dict[tuple[object, ...], dict[tuple[object, ...], int]] = {}

    def add_edge(left: tuple[object, ...], right: tuple[object, ...], capacity: int) -> None:
        residual.setdefault(left, {})[right] = capacity
        residual.setdefault(right, {}).setdefault(left, 0)

    for account_key, capacity in account_capacities.items():
        available = capacity - account_counts.get(account_key, 0)
        if available > 0:
            add_edge(source, ("account", account_key), available)
    for queued in jobs:
        if queued.requester_id not in requester_states:
            continue
        account_node = ("account", queued.account_key)
        if residual.get(source, {}).get(account_node, 0) <= 0:
            continue
        job_node = ("job", queued.job_id)
        matching_machines = [
            machine_id
            for machine_id, machine_slots in slots_by_machine.items()
            if any(_slot_matches(candidate, queued) for candidate in machine_slots)
        ]
        if not matching_machines:
            continue
        add_edge(account_node, job_node, 1)
        for machine_id in matching_machines:
            add_edge(job_node, ("machine", machine_id), 1)
    for machine_id in slots_by_machine:
        add_edge(("machine", machine_id), sink, 1)

    total = 0
    while True:
        parent: dict[tuple[object, ...], tuple[object, ...] | None] = {source: None}
        queue: deque[tuple[object, ...]] = deque([source])
        while queue and sink not in parent:
            left = queue.popleft()
            for right, capacity in residual.get(left, {}).items():
                if capacity > 0 and right not in parent:
                    parent[right] = left
                    queue.append(right)
        if sink not in parent:
            return total
        cursor = sink
        path_capacity = math.inf
        while parent[cursor] is not None:
            previous = parent[cursor]
            assert previous is not None
            path_capacity = min(path_capacity, residual[previous][cursor])
            cursor = previous
        amount = int(path_capacity)
        cursor = sink
        while parent[cursor] is not None:
            previous = parent[cursor]
            assert previous is not None
            residual[previous][cursor] -= amount
            residual[cursor][previous] += amount
            cursor = previous
        total += amount


def plan_dispatches(
    jobs: Sequence[Job],
    slots: Sequence[Slot],
    *,
    requester_states: Mapping[str, RequesterState],
    account_capacities: Mapping[str, int],
    account_running: Mapping[str, int] | None = None,
    next_dispatch_seq: int | None = None,
    max_dispatches: int | None = None,
) -> tuple[Dispatch, ...]:
    """Return a deterministic, fail-closed dispatch plan without mutating inputs.

    Missing requester state, account capacity, capability, freshness, or readiness
    makes a job ineligible. Malformed and duplicate identities raise ``ValueError``
    rather than guessing. Machine mutation capacity is deliberately fixed at one
    in this first safety model.
    """
    queued_jobs = tuple(jobs)
    known_slots = tuple(slots)
    running_input = {} if account_running is None else account_running
    _validate_inputs(
        queued_jobs,
        known_slots,
        requester_states,
        account_capacities,
        running_input,
        next_dispatch_seq=next_dispatch_seq,
        max_dispatches=max_dispatches,
    )

    limit = len(known_slots) if max_dispatches is None else max_dispatches
    if limit == 0:
        return ()
    sequence = (
        max((state.last_dispatch_seq for state in requester_states.values()), default=0) + 1
        if next_dispatch_seq is None
        else next_dispatch_seq
    )

    remaining = list(queued_jobs)
    unused_slots = list(known_slots)
    used_machines: set[str] = {
        candidate.machine_id
        for candidate in known_slots
        if candidate.fresh and candidate.state == "busy"
    }
    account_counts = {key: 0 for key in account_capacities}
    account_counts.update(running_input)
    dynamic_states = dict(requester_states)
    plan: list[Dispatch] = []

    while remaining and unused_slots and len(plan) < limit:
        eligible_by_requester: dict[str, list[tuple[Job, tuple[Slot, ...]]]] = {}
        for queued in remaining:
            state = dynamic_states.get(queued.requester_id)
            capacity = account_capacities.get(queued.account_key)
            if state is None or capacity is None:
                continue
            if account_counts[queued.account_key] >= capacity:
                continue
            compatible = tuple(
                candidate
                for candidate in unused_slots
                if candidate.machine_id not in used_machines and _slot_matches(candidate, queued)
            )
            if compatible:
                eligible_by_requester.setdefault(queued.requester_id, []).append((queued, compatible))

        if not eligible_by_requester:
            break

        oldest_by_requester: dict[str, tuple[Job, tuple[Slot, ...]]] = {
            requester_id: min(candidates, key=lambda item: (item[0].created_at, item[0].job_id))
            for requester_id, candidates in eligible_by_requester.items()
        }
        requester_id = min(
            oldest_by_requester,
            key=lambda rid: (
                dynamic_states[rid].active_count,
                dynamic_states[rid].last_dispatch_seq,
                oldest_by_requester[rid][0].created_at,
                rid,
            ),
        )
        queued, compatible = oldest_by_requester[requester_id]

        def future_capacity(candidate_slot: Slot) -> int:
            counts_after = dict(account_counts)
            counts_after[queued.account_key] += 1
            return _future_dispatch_capacity(
                [other for other in remaining if other.job_id != queued.job_id],
                unused_slots,
                requester_states=dynamic_states,
                account_capacities=account_capacities,
                account_counts=counts_after,
                excluded_machines=used_machines | {candidate_slot.machine_id},
            )

        selected_slot = min(
            compatible,
            key=lambda candidate: (
                -future_capacity(candidate),
                candidate.machine_id,
                candidate.slot_id,
            ),
        )

        plan.append(
            Dispatch(
                requester_id=requester_id,
                job_id=queued.job_id,
                slot_id=selected_slot.slot_id,
                machine_id=selected_slot.machine_id,
                account_key=queued.account_key,
                dispatch_seq=sequence,
            )
        )
        previous = dynamic_states[requester_id]
        dynamic_states[requester_id] = RequesterState(
            active_count=previous.active_count + 1,
            last_dispatch_seq=sequence,
        )
        account_counts[queued.account_key] += 1
        used_machines.add(selected_slot.machine_id)
        remaining = [candidate for candidate in remaining if candidate.job_id != queued.job_id]
        unused_slots = [candidate for candidate in unused_slots if candidate.slot_id != selected_slot.slot_id]
        sequence += 1

    return tuple(plan)
