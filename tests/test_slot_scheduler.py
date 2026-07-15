"""Issue #125: pure browser-slot fairness scheduler contract."""
from __future__ import annotations

import random

import pytest

from tools.multi_position_sourcing.slot_scheduler import (
    Dispatch,
    Job,
    RequesterState,
    Slot,
    plan_dispatches,
)


def job(
    requester: str,
    job_id: int,
    created_at: int,
    *,
    resource_class: str = "browser",
    requirements: dict[str, object] | None = None,
    requested_machine: str | None = None,
    account_key: str = "portal:saramin",
) -> Job:
    return Job(
        requester_id=requester,
        job_id=job_id,
        created_at=created_at,
        resource_class=resource_class,
        requirements=requirements or {},
        requested_machine=requested_machine,
        account_key=account_key,
    )


def slot(
    slot_id: str,
    machine_id: str,
    *,
    resource_class: str = "browser",
    capabilities: dict[str, object] | None = None,
    account_key: str = "portal:saramin",
    state: str = "ready",
    fresh: bool = True,
) -> Slot:
    return Slot(
        slot_id=slot_id,
        machine_id=machine_id,
        resource_class=resource_class,
        capabilities=capabilities or {},
        account_key=account_key,
        state=state,
        fresh=fresh,
    )


def states(*requesters: str) -> dict[str, RequesterState]:
    return {name: RequesterState(active_count=0, last_dispatch_seq=0) for name in requesters}


def signature(plan: tuple[Dispatch, ...]) -> tuple[tuple[object, ...], ...]:
    return tuple(
        (d.requester_id, d.job_id, d.slot_id, d.account_key, d.dispatch_seq)
        for d in plan
    )


def test_three_machines_four_requesters_five_heterogeneous_slots_are_fair():
    jobs = [job(name, i, i) for i, name in enumerate(("a", "b", "c", "d"), 1)]
    slots = [
        slot("macmini-saramin", "macmini", capabilities={"portal": "saramin"}),
        slot("macmini-jobkorea", "macmini", capabilities={"portal": "jobkorea"}),
        slot("macbook-browser", "macbook"),
        slot("winpc-browser", "winpc"),
        slot("winpc-extra", "winpc", state="parked"),
    ]

    plan = plan_dispatches(
        jobs,
        slots,
        requester_states=states("a", "b", "c", "d"),
        account_capacities={"portal:saramin": 4},
    )

    assert len(plan) == 3
    assert len({d.machine_id for d in plan}) == 3

    # Across four one-at-a-time claims/releases, every continuously backlogged
    # requester is served before any requester receives a second dispatch.
    pending = jobs[:]
    requester_states = states("a", "b", "c", "d")
    first_round = []
    for dispatch_seq in range(1, 5):
        one = plan_dispatches(
            pending,
            slots,
            requester_states=requester_states,
            account_capacities={"portal:saramin": 4},
            next_dispatch_seq=dispatch_seq,
            max_dispatches=1,
        )
        assert len(one) == 1
        dispatched = one[0]
        first_round.append(dispatched.requester_id)
        pending = [candidate for candidate in pending if candidate.job_id != dispatched.job_id]
        requester_states[dispatched.requester_id] = RequesterState(
            active_count=0, last_dispatch_seq=dispatched.dispatch_seq)
    assert set(first_round) == {"a", "b", "c", "d"}


def test_requester_fifo_uses_created_at_then_job_id():
    jobs = [job("a", 30, 2), job("a", 20, 1), job("a", 10, 1)]
    plan = plan_dispatches(
        jobs,
        [slot(f"s{i}", f"m{i}") for i in range(3)],
        requester_states=states("a"),
        account_capacities={"portal:saramin": 3},
    )
    assert [d.job_id for d in plan] == [10, 20, 30]


def test_ineligible_head_job_does_not_block_eligible_job():
    jobs = [
        job("a", 1, 1, requirements={"portal": "linkedin"}),
        job("a", 2, 2, requirements={"portal": "saramin"}),
    ]
    plan = plan_dispatches(
        jobs,
        [slot("s1", "macmini", capabilities={"portal": "saramin"})],
        requester_states=states("a"),
        account_capacities={"portal:saramin": 1},
    )
    assert [d.job_id for d in plan] == [2]


def test_requested_machine_and_resource_class_are_enforced():
    jobs = [
        job("a", 1, 1, requested_machine="winpc"),
        job("b", 2, 2, resource_class="linkedin_rps", account_key="portal:linkedin_rps"),
    ]
    plan = plan_dispatches(
        jobs,
        [slot("mac", "macmini"), slot("rps", "winpc", resource_class="linkedin_rps", account_key="portal:linkedin_rps")],
        requester_states=states("a", "b"),
        account_capacities={"portal:saramin": 1, "portal:linkedin_rps": 1},
    )
    assert [(d.job_id, d.slot_id) for d in plan] == [(2, "rps")]


def test_two_rps_tabs_still_obey_single_account_capacity():
    rps_jobs = [
        job("a", 1, 1, resource_class="linkedin_rps", account_key="portal:linkedin_rps"),
        job("b", 2, 2, resource_class="linkedin_rps", account_key="portal:linkedin_rps"),
    ]
    rps_slots = [
        slot("winpc:rps:tab-1", "winpc", resource_class="linkedin_rps", account_key="portal:linkedin_rps"),
        slot("winpc:rps:tab-2", "winpc", resource_class="linkedin_rps", account_key="portal:linkedin_rps"),
    ]
    plan = plan_dispatches(
        rps_jobs,
        rps_slots,
        requester_states=states("a", "b"),
        account_capacities={"portal:linkedin_rps": 1},
    )
    assert len(plan) == 1


@pytest.mark.parametrize("challenge_fresh", [True, False])
def test_challenge_blocks_same_account_across_all_slots(challenge_fresh):
    plan = plan_dispatches(
        [
            job(
                "rps",
                1,
                1,
                resource_class="linkedin_rps",
                account_key="portal:linkedin_rps",
            ),
            job("saramin", 2, 2),
        ],
        [
            slot(
                "challenged",
                "m1",
                resource_class="linkedin_rps",
                account_key="portal:linkedin_rps",
                state="challenge",
                fresh=challenge_fresh,
            ),
            slot(
                "ready-rps",
                "m2",
                resource_class="linkedin_rps",
                account_key="portal:linkedin_rps",
            ),
            slot("ready-saramin", "m3"),
        ],
        requester_states=states("rps", "saramin"),
        account_capacities={"portal:linkedin_rps": 1, "portal:saramin": 1},
    )
    assert [(d.job_id, d.slot_id) for d in plan] == [(2, "ready-saramin")]


def test_machine_default_capacity_allows_only_one_mutating_slot():
    plan = plan_dispatches(
        [job("a", 1, 1), job("b", 2, 2)],
        [slot("tab-1", "winpc"), slot("tab-2", "winpc")],
        requester_states=states("a", "b"),
        account_capacities={"portal:saramin": 2},
    )
    assert len(plan) == 1


def test_existing_account_usage_reduces_available_capacity():
    plan = plan_dispatches(
        [job("a", 1, 1)],
        [slot("s1", "macmini")],
        requester_states=states("a"),
        account_capacities={"portal:saramin": 1},
        account_running={"portal:saramin": 1},
    )
    assert plan == ()


def test_shuffle_inputs_one_hundred_times_has_identical_plan():
    jobs = [job(name, i, i // 2, requirements={"portal": "saramin"}) for i, name in enumerate("aabbccdd", 1)]
    slots = [slot(f"s{i}", f"m{i % 3}", capabilities={"portal": "saramin", "rank": i}) for i in range(1, 6)]
    kwargs = dict(
        requester_states=states("a", "b", "c", "d"),
        account_capacities={"portal:saramin": 5},
    )
    expected = signature(plan_dispatches(jobs, slots, **kwargs))
    rng = random.Random(125)
    for _ in range(100):
        shuffled_jobs = jobs[:]
        shuffled_slots = slots[:]
        rng.shuffle(shuffled_jobs)
        rng.shuffle(shuffled_slots)
        assert signature(plan_dispatches(shuffled_jobs, shuffled_slots, **kwargs)) == expected


def test_stale_parked_and_unknown_capability_slots_fail_closed():
    jobs = [job("a", 1, 1, requirements={"portal": "saramin"})]
    slots = [
        slot("stale", "m1", capabilities={"portal": "saramin"}, fresh=False),
        slot("parked", "m2", capabilities={"portal": "saramin"}, state="parked"),
        slot("unknown", "m3", capabilities={}),
    ]
    assert plan_dispatches(
        jobs,
        slots,
        requester_states=states("a"),
        account_capacities={"portal:saramin": 1},
    ) == ()


@pytest.mark.parametrize(
    "jobs,slots,requester_states,capacities",
    [
        ([job("", 1, 1)], [slot("s", "m")], {}, {"portal:saramin": 1}),
        ([job("a", 0, 1)], [slot("s", "m")], states("a"), {"portal:saramin": 1}),
        ([job("a", 1, 1), job("b", 1, 2)], [slot("s", "m")], states("a", "b"), {"portal:saramin": 1}),
        ([job("a", 1, 1)], [slot("s", "m"), slot("s", "m2")], states("a"), {"portal:saramin": 1}),
        ([job("a", 1, 1)], [slot("", "m")], states("a"), {"portal:saramin": 1}),
        ([job("a", 1, 1)], [slot("s", "")], states("a"), {"portal:saramin": 1}),
        ([job("a", 1, 1)], [slot("s", "m")], states("a"), {"portal:saramin": 0}),
    ],
)
def test_malformed_or_duplicate_input_is_rejected(jobs, slots, requester_states, capacities):
    with pytest.raises(ValueError):
        plan_dispatches(jobs, slots, requester_states=requester_states, account_capacities=capacities)


def test_missing_requester_state_and_account_capacity_fail_closed():
    assert plan_dispatches(
        [job("missing", 1, 1)],
        [slot("s", "m")],
        requester_states={},
        account_capacities={"portal:saramin": 1},
    ) == ()
    assert plan_dispatches(
        [job("a", 1, 1, account_key="unknown")],
        [slot("s", "m", account_key="unknown")],
        requester_states=states("a"),
        account_capacities={},
    ) == ()


def test_seeded_ten_thousand_scenarios_have_no_collision_or_starvation():
    rng = random.Random(10_000)
    for seed in range(10_000):
        requesters = ("a", "b", "c", "d")
        backlog = [job(r, seed * 100 + n * 4 + i + 1, n) for n in range(3) for i, r in enumerate(requesters)]
        slots = [slot(f"{seed}:s{i}", f"m{i}") for i in range(4)]
        rng.shuffle(backlog)
        rng.shuffle(slots)
        plan = plan_dispatches(
            backlog,
            slots,
            requester_states=states(*requesters),
            account_capacities={"portal:saramin": 4},
        )
        assert len({d.slot_id for d in plan}) == len(plan), f"seed={seed} duplicate slot"
        assert len({d.machine_id for d in plan}) == len(plan), f"seed={seed} duplicate machine"
        assert len({d.job_id for d in plan}) == len(plan), f"seed={seed} duplicate job"
        served = {r: sum(d.requester_id == r for d in plan) for r in requesters}
        assert max(served.values()) - min(served.values()) <= 1, f"seed={seed} unfair {served}"
        assert all(value == 1 for value in served.values()), f"seed={seed} starvation {served}"


def test_active_count_and_last_dispatch_sequence_drive_requester_order():
    plan = plan_dispatches(
        [job("a", 1, 1), job("b", 2, 2), job("c", 3, 3)],
        [slot("s", "m")],
        requester_states={
            "a": RequesterState(active_count=1, last_dispatch_seq=0),
            "b": RequesterState(active_count=0, last_dispatch_seq=10),
            "c": RequesterState(active_count=0, last_dispatch_seq=5),
        },
        account_capacities={"portal:saramin": 1},
        next_dispatch_seq=11,
    )
    assert [(d.requester_id, d.dispatch_seq) for d in plan] == [("c", 11)]



@pytest.mark.parametrize("busy_fresh", [True, False])
def test_busy_sibling_slot_blocks_new_machine_dispatch(busy_fresh):
    plan = plan_dispatches(
        [job("a", 1, 1)],
        [
            slot(
                "already-writing",
                "m1",
                account_key="portal:other",
                state="busy",
                fresh=busy_fresh,
            ),
            slot("ready-sibling", "m1"),
        ],
        requester_states=states("a"),
        account_capacities={"portal:saramin": 1, "portal:other": 1},
        account_running={"portal:other": 1},
    )
    assert plan == ()


def test_linkedin_rps_capacity_cannot_be_raised_by_caller():
    rps_jobs = [
        job("a", 1, 1, resource_class="linkedin_rps", account_key="portal:linkedin_rps"),
        job("b", 2, 2, resource_class="linkedin_rps", account_key="portal:linkedin_rps"),
    ]
    rps_slots = [
        slot("rps-1", "m1", resource_class="linkedin_rps", account_key="portal:linkedin_rps"),
        slot("rps-2", "m2", resource_class="linkedin_rps", account_key="portal:linkedin_rps"),
    ]
    with pytest.raises(ValueError):
        plan_dispatches(
            rps_jobs,
            rps_slots,
            requester_states=states("a", "b"),
            account_capacities={"portal:linkedin_rps": 2},
        )


def test_unconstrained_job_does_not_strand_requested_machine_job():
    plan = plan_dispatches(
        [job("a", 1, 1), job("b", 2, 2, requested_machine="m1")],
        [slot("s1", "m1"), slot("s2", "m2")],
        requester_states=states("a", "b"),
        account_capacities={"portal:saramin": 2},
    )
    assert [(d.job_id, d.machine_id) for d in plan] == [(1, "m2"), (2, "m1")]


def test_unconstrained_job_does_not_strand_capability_job():
    plan = plan_dispatches(
        [job("a", 1, 1), job("b", 2, 2, requirements={"only": "yes"})],
        [
            slot("special", "m1", capabilities={"only": "yes"}),
            slot("general", "m2", capabilities={"x": 1, "y": 2}),
        ],
        requester_states=states("a", "b"),
        account_capacities={"portal:saramin": 2},
    )
    assert [(d.job_id, d.machine_id) for d in plan] == [(1, "m2"), (2, "m1")]


def test_next_dispatch_sequence_must_advance_existing_state():
    with pytest.raises(ValueError):
        plan_dispatches(
            [job("a", 1, 1)],
            [slot("s", "m")],
            requester_states={"a": RequesterState(active_count=0, last_dispatch_seq=10)},
            account_capacities={"portal:saramin": 1},
            next_dispatch_seq=10,
        )


def test_capability_values_match_with_exact_json_types():
    assert plan_dispatches(
        [job("a", 1, 1, requirements={"human_idle": True})],
        [slot("s", "m", capabilities={"human_idle": 1})],
        requester_states=states("a"),
        account_capacities={"portal:saramin": 1},
    ) == ()

    with pytest.raises(ValueError):
        plan_dispatches(
            [job("a", 1, 1)],
            [slot("s", "m", capabilities={"opaque": object()})],
            requester_states=states("a"),
            account_capacities={"portal:saramin": 1},
        )


def test_slot_choice_preserves_maximum_future_matching_capacity():
    plan = plan_dispatches(
        [
            job("a", 1, 0),
            job("b", 2, 1, requirements={"x": 0}),
            job("c", 3, 2, requirements={"y": 0}),
        ],
        [
            slot("s0", "m0", capabilities={"x": 0}),
            slot("s1", "m1", capabilities={"x": 1, "y": 0}),
            slot("s2", "m2", capabilities={"y": 0}),
        ],
        requester_states=states("a", "b", "c"),
        account_capacities={"portal:saramin": 3},
    )
    assert len(plan) == 3
    assert [(d.job_id, d.machine_id) for d in plan] == [
        (1, "m1"),
        (2, "m0"),
        (3, "m2"),
    ]
