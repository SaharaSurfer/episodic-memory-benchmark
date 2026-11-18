from dataclasses import replace
from decimal import Decimal

import pytest

from mbench.core.legality.predicate import Reason, Refusal
from mbench.core.values.protocol import ValueClass
from tests.core.world import (
    OPENED_IN,
    OPENING_RATE,
    World,
    change_fee,
    reprice,
)
from tests.testpack.values import InterestRate, MonetaryAmount


def test_a_mutate_in_the_session_of_the_init_is_refused() -> None:
    world = World()
    account = world.open()

    outcome = world.decide(reprice(account, OPENED_IN, "3.90"))

    assert outcome == Refusal(clause=2, reason=Reason.PAIR_ALREADY_WRITTEN)


def test_a_second_mutate_of_one_pair_in_one_session_is_refused() -> None:
    world = World()
    account = world.open()
    world.accept(reprice(account, 2, "3.90"))

    outcome = world.decide(reprice(account, 2, "3.50"))

    assert outcome == Refusal(clause=2, reason=Reason.PAIR_ALREADY_WRITTEN)


def test_a_mutate_of_another_pair_in_the_same_session_is_accepted() -> None:
    world = World()
    account = world.open()
    world.accept(reprice(account, 2, "3.90"))

    outcome = world.decide(change_fee(account, 2, "0"))

    assert not isinstance(outcome, Refusal)


def test_the_same_pair_of_another_entity_in_the_session_is_accepted() -> None:
    world = World()
    account = world.open()
    other = world.open()
    world.accept(reprice(account, 2, "3.90"))

    outcome = world.decide(reprice(other, 2, "3.90"))

    assert not isinstance(outcome, Refusal)


@pytest.mark.parametrize(
    "value",
    [InterestRate(Decimal("100")), MonetaryAmount(Decimal("3.90"))],
    ids=["invalid value", "value of another class"],
)
def test_a_mutate_value_its_relation_does_not_hold_is_refused(
    value: ValueClass,
) -> None:
    world = World()
    account = world.open()
    command = replace(reprice(account, 2, "3.90"), value=value)

    outcome = world.decide(command)

    assert outcome == Refusal(clause=3, reason=Reason.INVALID_VALUE)


def test_a_first_write_of_a_relation_the_entity_lacks_is_accepted() -> None:
    world = World()
    account = world.open_lacking("hasInterestRate")

    outcome = world.decide(reprice(account, 2, "3.90"))

    assert not isinstance(outcome, Refusal)


def test_a_mutate_to_the_pairs_current_value_is_refused() -> None:
    world = World()
    account = world.open()

    outcome = world.decide(reprice(account, 2, OPENING_RATE))

    assert outcome == Refusal(clause=8, reason=Reason.UNCHANGED_VALUE)


def test_the_current_value_is_the_latest_write_not_the_first() -> None:
    world = World()
    account = world.open()
    world.accept(reprice(account, 2, "3.90"))

    unchanged = world.decide(reprice(account, 3, "3.90"))
    back_to_first = world.decide(reprice(account, 3, OPENING_RATE))

    assert unchanged == Refusal(clause=8, reason=Reason.UNCHANGED_VALUE)
    assert not isinstance(back_to_first, Refusal)


@pytest.mark.parametrize(
    "rate",
    [OPENING_RATE, "100"],
    ids=["also unchanged (clause 8)", "also invalid (clause 3)"],
)
def test_a_command_failing_several_clauses_names_the_first(rate: str) -> None:
    world = World()
    account = world.open()

    outcome = world.decide(reprice(account, OPENED_IN, rate))

    assert outcome == Refusal(clause=2, reason=Reason.PAIR_ALREADY_WRITTEN)
