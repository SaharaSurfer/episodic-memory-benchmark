from dataclasses import replace

import pytest

from mbench.core.legality.predicate import (
    Reason,
    Refusal,
    refuse_illegal_contest,
)
from mbench.core.records.log import MutateEvent
from mbench.packs.spec import (
    Framing,
    Gate,
    LoadedPack,
    MutateAction,
    Source,
    SourceKind,
)
from tests.core.world import (
    BANK_MAY_CLOSE,
    OPENING_RATE,
    World,
    contest,
    disclosures_in,
    reprice,
    status_contest,
    with_framings,
)
from tests.testpack.pack import LOADED_PACK
from tests.testpack.values import (
    CLOSED,
    FROZEN,
    INACTIVE,
    DepositKind,
    LifecycleStatus,
)

RATE = "hasInterestRate"
CONTESTED_IN = 7
A = "3.75"
B = "3.60"
REPRICED = "3.90"
REPRICED_IN = 5


@pytest.mark.parametrize(
    "sources",
    [("letter", "operator"), ("operator", "letter"), ("customer", "operator")],
)
def test_two_sources_of_unequal_authority_are_refused(
    sources: tuple[str, str],
) -> None:
    world = World()
    account = world.open()

    outcome = world.decide(contest(account, CONTESTED_IN, A, B, sources))

    assert outcome == Refusal(5, Reason.UNEQUAL_AUTHORITY)


@pytest.mark.parametrize("speaker", ["customer", "operator"])
def test_one_speaker_twice_is_refused(speaker: str) -> None:
    world = World()
    account = world.open()
    command = contest(account, CONTESTED_IN, A, B, (speaker, speaker))

    assert world.decide(command) == Refusal(5, Reason.SPEAKER_TWICE)


@pytest.mark.parametrize(
    "sources", [("operator", "letter"), ("customer", "operator")]
)
def test_two_different_sources_of_equal_authority_are_accepted(
    sources: tuple[str, str],
) -> None:
    tied = {
        **LOADED_PACK.sources,
        "customer": Source("customer", SourceKind.SPEAKER, authority=2),
        "operator": Source("operator", SourceKind.SPEAKER, authority=2),
    }
    world = World(replace(LOADED_PACK, sources=tied))
    account = world.open()

    records = world.accept(contest(account, CONTESTED_IN, A, B, sources))

    assert [d.source for d in disclosures_in(records)] == list(sources)


def test_a_equal_to_b_is_refused() -> None:
    world = World()
    account = world.open()

    outcome = world.decide(contest(account, CONTESTED_IN, A, A))

    assert outcome == Refusal(5, Reason.CONTESTED_VALUES_EQUAL)


@pytest.mark.parametrize(
    ("a", "b"), [(REPRICED, B), (A, REPRICED)], ids=["a", "b"]
)
def test_either_value_equal_to_the_current_one_is_refused(
    a: str, b: str
) -> None:
    world = World()
    account = world.open()
    world.accept(reprice(account, REPRICED_IN, REPRICED))

    outcome = world.decide(contest(account, CONTESTED_IN, a, b))

    assert outcome == Refusal(5, Reason.CONTESTED_VALUE_IS_CURRENT)


def test_a_value_only_an_earlier_version_held_is_not_refused_here() -> None:
    world = World()
    account = world.open()
    world.accept(reprice(account, REPRICED_IN, REPRICED))

    outcome = world.decide(contest(account, CONTESTED_IN, OPENING_RATE, B))

    assert not isinstance(outcome, Refusal)


def _with_gate(pack: LoadedPack, name: str, gate: Gate) -> LoadedPack:
    """The pack with the named ActionType's gate extended."""

    action = pack.action_types[name]
    assert isinstance(action, MutateAction)
    gated = replace(action, gate={**action.gate, **gate})

    return replace(pack, action_types={**pack.action_types, name: gated})


CHECKING_ONLY: Gate = {"kind": frozenset({DepositKind("checking")})}


@pytest.mark.parametrize(
    ("a", "b"), [(INACTIVE, FROZEN), (FROZEN, INACTIVE)], ids=["a", "b"]
)
def test_a_value_no_action_can_write_from_the_current_one_is_refused(
    a: LifecycleStatus, b: LifecycleStatus
) -> None:
    world = World()
    account = world.open()

    outcome = world.decide(status_contest(account, CONTESTED_IN, a, b))

    assert outcome == Refusal(5, Reason.NO_WRITER)


def test_a_pair_holding_no_value_has_nothing_to_write_from() -> None:
    world = World()
    account = world.open_lacking(RATE)

    outcome = world.decide(contest(account, CONTESTED_IN, A, B))

    assert outcome == Refusal(5, Reason.NO_WRITER)


@pytest.mark.parametrize(
    ("a", "b"), [(FROZEN, CLOSED), (CLOSED, FROZEN)], ids=["a", "b"]
)
def test_a_value_whose_action_fails_its_gate_is_refused(
    a: LifecycleStatus, b: LifecycleStatus
) -> None:
    pack = _with_gate(BANK_MAY_CLOSE, "FREEZE_DEPOSIT_ACCOUNT", CHECKING_ONLY)
    world = World(pack)
    account = world.open()

    outcome = world.decide(status_contest(account, CONTESTED_IN, a, b))

    assert outcome == Refusal(5, Reason.WRITER_GATE_FAILED)


def test_a_value_whose_action_passes_its_gate_is_accepted() -> None:
    pack = _with_gate(BANK_MAY_CLOSE, "FREEZE_DEPOSIT_ACCOUNT", CHECKING_ONLY)
    world = World(pack)
    account = world.open(kind=DepositKind("checking"))

    records = world.accept(
        status_contest(account, CONTESTED_IN, FROZEN, CLOSED)
    )

    assert [(d.value, d.action_type) for d in disclosures_in(records)] == [
        (FROZEN, "FREEZE_DEPOSIT_ACCOUNT"),
        (CLOSED, "CLOSE_DEPOSIT_ACCOUNT"),
    ]


@pytest.mark.parametrize(
    ("a", "b"), [(FROZEN, CLOSED), (CLOSED, FROZEN)], ids=["a", "b"]
)
def test_a_status_move_the_owner_states_cannot_be_contested(
    a: LifecycleStatus, b: LifecycleStatus
) -> None:
    # The bank starts both moves, so only who states the closing is at fault.
    world = World(
        with_framings(CLOSE_DEPOSIT_ACCOUNT=(Framing("BANK", "customer"),))
    )
    account = world.open()

    outcome = world.decide(status_contest(account, CONTESTED_IN, a, b))

    assert outcome == Refusal(5, Reason.NO_CONTESTABLE_FRAMING)


@pytest.mark.parametrize(
    ("a", "b"), [(FROZEN, CLOSED), (CLOSED, FROZEN)], ids=["a", "b"]
)
def test_values_whose_framings_share_no_initiator_are_refused(
    a: LifecycleStatus, b: LifecycleStatus
) -> None:
    world = World(
        with_framings(CLOSE_DEPOSIT_ACCOUNT=(Framing("CLIENT", "letter"),))
    )
    account = world.open()

    outcome = world.decide(status_contest(account, CONTESTED_IN, a, b))

    assert outcome == Refusal(5, Reason.INITIATOR_NOT_SHARED)


def test_a_command_naming_an_initiator_not_shared_is_refused() -> None:
    world = World(BANK_MAY_CLOSE)
    account = world.open()
    command = replace(
        status_contest(account, CONTESTED_IN, FROZEN, CLOSED),
        initiator="CLIENT",
    )

    assert world.decide(command) == Refusal(5, Reason.INITIATOR_NOT_SHARED)


@pytest.mark.parametrize("initiator", ["BANK", "CLIENT"])
def test_the_event_and_disclosures_take_the_shared_initiator_named(
    initiator: str,
) -> None:
    both = (Framing("BANK", "letter"), Framing("CLIENT", "email"))
    world = World(
        with_framings(FREEZE_DEPOSIT_ACCOUNT=both, CLOSE_DEPOSIT_ACCOUNT=both)
    )
    account = world.open()
    command = replace(
        status_contest(account, CONTESTED_IN, FROZEN, CLOSED),
        initiator=initiator,
    )

    records = world.accept(command)

    event = records[0]
    assert isinstance(event, MutateEvent)
    assert event.initiator == initiator
    assert {d.initiator for d in disclosures_in(records)} == {initiator}


def test_this_clause_does_not_refuse_a_pair_already_contested() -> None:
    world = World()
    account = world.open()
    world.accept(contest(account, CONTESTED_IN, A, B))
    again = contest(account, CONTESTED_IN + 1, REPRICED, OPENING_RATE)

    assert refuse_illegal_contest(again, world.registry, world.pack) is None
