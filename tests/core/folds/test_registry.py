from dataclasses import replace
from decimal import Decimal

import pytest

from mbench.core.folds.registry import (
    Entry,
    Liveness,
    Stamped,
    contested_relations,
    held_values,
    liveness,
    true_value,
    true_values,
)
from mbench.core.records.ids import NodeId
from mbench.core.values.contested import Contested, WorldValue
from mbench.packs.spec import EntityType
from tests.testpack.pack import DEPOSIT_ACCOUNT, LOADED_PACK
from tests.testpack.values import ACTIVE, CLOSED, DepositKind, MonetaryAmount

CHECKING = DepositKind("checking")
SAVINGS = DepositKind("savings")

# A type with no status, so liveness has nothing to read on it.
COUNTER = EntityType("COUNTER", relations={"amount": MonetaryAmount})
WITH_COUNTER = replace(
    LOADED_PACK,
    entity_types={**LOADED_PACK.entity_types, COUNTER.name: COUNTER},
)


def _account(**values: WorldValue) -> Entry:
    """A deposit account holding exactly the values, keyed by relation."""

    return Entry(
        DEPOSIT_ACCOUNT.name,
        NodeId("acct1"),
        {relation: Stamped(value, 1) for relation, value in values.items()},
    )


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (ACTIVE, Liveness.LIVE),
        (CLOSED, Liveness.TERMINAL),
        (Contested(ACTIVE, CLOSED), Liveness.UNDECIDED),
    ],
    ids=["live", "terminal", "contested"],
)
def test_liveness_reads_the_status(
    status: WorldValue, expected: Liveness
) -> None:
    entry = _account(hasStatus=status)

    assert liveness(entry, LOADED_PACK) is expected


def test_liveness_of_a_type_with_no_status_is_live() -> None:
    entry = Entry(COUNTER.name, NodeId("cnt01"), {})

    assert liveness(entry, WITH_COUNTER) is Liveness.LIVE


def test_a_plain_value_is_true_and_the_only_one_held() -> None:
    entry = _account(kind=CHECKING)

    assert true_value(entry, "kind") == CHECKING
    assert held_values(entry, "kind") == {CHECKING}


def test_a_contested_value_has_no_truth_but_holds_both_sides() -> None:
    entry = _account(kind=Contested(CHECKING, SAVINGS))

    assert true_value(entry, "kind") is None
    assert held_values(entry, "kind") == {CHECKING, SAVINGS}


def test_an_absent_relation_has_no_truth_and_holds_nothing() -> None:
    entry = _account()

    assert true_value(entry, "kind") is None
    assert held_values(entry, "kind") == frozenset()


def test_an_entity_with_no_conflict_has_no_contested_relations() -> None:
    entry = _account(kind=CHECKING, hasStatus=ACTIVE)

    assert contested_relations(entry) == frozenset()


def test_contested_relations_are_exactly_the_contested_pairs() -> None:
    entry = _account(
        kind=Contested(CHECKING, SAVINGS),
        hasStatus=Contested(ACTIVE, CLOSED),
        hasMonthlyFee=MonetaryAmount(Decimal("5.00")),
    )

    assert contested_relations(entry) == {"kind", "hasStatus"}


def test_true_values_leave_out_the_contested_relations() -> None:
    fee = MonetaryAmount(Decimal("5.00"))
    entry = _account(
        kind=Contested(CHECKING, SAVINGS), hasStatus=ACTIVE, hasMonthlyFee=fee
    )

    assert true_values(entry) == {"hasStatus": ACTIVE, "hasMonthlyFee": fee}
