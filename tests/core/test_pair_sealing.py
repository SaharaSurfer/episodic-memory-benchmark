from collections.abc import Callable
from decimal import Decimal

import pytest

from mbench.core.legality.predicate import Reason, Refusal
from mbench.core.records.commands import (
    Command,
    ConflictingDoubleDisclosureCommand,
)
from mbench.core.records.ids import NodeId
from tests.core.world import (
    BANK_MAY_CLOSE,
    OPENING_RATE,
    World,
    agree,
    change_fee,
    contest,
    issue,
    move,
    read,
    reprice,
    status_contest,
    with_gate,
)
from tests.testpack.pack import LOADED_PACK
from tests.testpack.values import ACTIVE, CLOSED, FROZEN, MonetaryAmount

CONTESTED_IN = 7
LATER = CONTESTED_IN + 2
A = "3.75"
B = "3.60"
FRESH = "3.90"
SEALED = Refusal(6, Reason.PAIR_SEALED)


def _contested_account(world: World) -> NodeId:
    """An account opened in the world, its rate then contested."""

    account = world.open()
    world.accept(contest(account, CONTESTED_IN, A, B))

    return account


def _fee_contest(account: NodeId) -> ConflictingDoubleDisclosureCommand:
    """A later command in which two sources state different fees."""

    return ConflictingDoubleDisclosureCommand(
        session=LATER,
        initiator="BANK",
        referent=account,
        relation="hasMonthlyFee",
        a=MonetaryAmount(Decimal("7")),
        b=MonetaryAmount(Decimal("9")),
        sources=("letter", "email"),
    )


def test_a_later_write_to_the_contested_pair_is_refused() -> None:
    world = World()
    account = _contested_account(world)

    assert world.decide(reprice(account, LATER, FRESH)) == SEALED


def test_a_dead_referent_is_refused_before_its_contested_pair_is() -> None:
    world = World()
    account = _contested_account(world)
    world.accept(move(account, LATER, "CLOSE_DEPOSIT_ACCOUNT"))

    outcome = world.decide(reprice(account, LATER + 1, FRESH))

    assert outcome == Refusal(1, Reason.NOT_LIVE)


def test_a_gate_on_another_pair_is_judged_before_sealing() -> None:
    world = World(
        with_gate(
            LOADED_PACK,
            "REPRICE_DEPOSIT_ACCOUNT",
            {"hasStatus": frozenset({ACTIVE})},
        )
    )
    account = _contested_account(world)
    world.accept(move(account, LATER, "FREEZE_DEPOSIT_ACCOUNT"))

    outcome = world.decide(reprice(account, LATER + 1, FRESH))

    assert outcome == Refusal(1, Reason.GATE_FAILED)


def test_a_later_read_that_would_disclose_the_pair_is_refused() -> None:
    world = World()
    account = _contested_account(world)

    assert world.decide(read(account, LATER)) == SEALED


@pytest.mark.parametrize(
    ("a", "b"),
    [(FRESH, OPENING_RATE), (A, B)],
    ids=["other values", "the same two"],
)
def test_a_second_contested_write_on_the_pair_is_refused(
    a: str, b: str
) -> None:
    world = World()
    account = _contested_account(world)

    assert world.decide(contest(account, LATER, a, b)) == SEALED


def test_a_later_status_move_is_refused_as_sealed_not_by_its_gate() -> None:
    world = World(BANK_MAY_CLOSE)
    account = world.open()
    world.accept(status_contest(account, CONTESTED_IN, FROZEN, CLOSED))

    outcome = world.decide(move(account, LATER, "FREEZE_DEPOSIT_ACCOUNT"))

    assert outcome == SEALED


def test_unequal_sources_on_a_contested_pair_stay_a_source_fault() -> None:
    world = World()
    account = _contested_account(world)
    command = contest(account, LATER, FRESH, A, ("letter", "operator"))

    assert world.decide(command) == Refusal(5, Reason.UNEQUAL_AUTHORITY)


def test_equal_values_on_a_contested_pair_stay_a_value_fault() -> None:
    world = World()
    account = _contested_account(world)

    outcome = world.decide(contest(account, LATER, FRESH, FRESH))

    assert outcome == Refusal(5, Reason.CONTESTED_VALUES_EQUAL)


def test_a_later_agreeing_double_disclosure_on_the_pair_is_refused() -> None:
    world = World()
    account = _contested_account(world)

    assert world.decide(agree(account, LATER, A)) == SEALED


@pytest.mark.parametrize(
    "make_command",
    [
        lambda account: change_fee(account, LATER, "7"),
        lambda account: move(account, LATER, "FREEZE_DEPOSIT_ACCOUNT"),
        _fee_contest,
    ],
    ids=["a value", "the status", "a contested write"],
)
def test_another_pair_of_the_entity_can_still_be_written(
    make_command: Callable[[NodeId], Command],
) -> None:
    world = World()
    account = _contested_account(world)

    assert not isinstance(world.decide(make_command(account)), Refusal)


def test_the_entity_can_still_be_named_as_an_endpoint() -> None:
    world = World()
    account = _contested_account(world)

    outcome = world.decide(issue(account, LATER))

    assert not isinstance(outcome, Refusal)


def test_a_read_of_an_entity_linked_to_the_sealed_one_is_accepted() -> None:
    world = World()
    account = world.open()
    card = world.issue_card(account)
    world.accept(contest(account, CONTESTED_IN, A, B))

    assert not isinstance(world.decide(read(card, LATER)), Refusal)


def test_sealing_one_entity_leaves_the_same_pair_of_another_writable() -> None:
    world = World()
    _contested_account(world)
    other = world.open()

    assert not isinstance(world.decide(reprice(other, LATER, FRESH)), Refusal)


def test_sealing_one_entity_leaves_another_readable() -> None:
    world = World()
    _contested_account(world)
    other = world.open()

    assert not isinstance(world.decide(read(other, LATER)), Refusal)
