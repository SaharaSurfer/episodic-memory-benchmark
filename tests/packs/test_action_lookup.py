from decimal import Decimal

import pytest

from mbench.core.values.protocol import ValueClass
from tests.testpack.pack import DEPOSIT_ACCOUNT, LOADED_PACK
from tests.testpack.values import InterestRate, LifecycleStatus, MonetaryAmount

ACTIVE = LifecycleStatus("active")
FROZEN = LifecycleStatus("frozen")
CLOSED = LifecycleStatus("closed")


@pytest.mark.parametrize(
    ("relation", "transition", "expected"),
    [
        ("hasStatus", (ACTIVE, FROZEN), "FREEZE_DEPOSIT_ACCOUNT"),
        ("hasStatus", (FROZEN, ACTIVE), "UNFREEZE_DEPOSIT_ACCOUNT"),
        ("hasStatus", (ACTIVE, CLOSED), "CLOSE_DEPOSIT_ACCOUNT"),
        ("hasStatus", (FROZEN, CLOSED), "CLOSE_DEPOSIT_ACCOUNT"),
        (
            "hasInterestRate",
            (InterestRate(Decimal("4.25")), InterestRate(Decimal("3.90"))),
            "REPRICE_DEPOSIT_ACCOUNT",
        ),
        (
            "hasMonthlyFee",
            (MonetaryAmount(Decimal("5")), MonetaryAmount(Decimal("0"))),
            "CHANGE_ACCOUNT_FEE",
        ),
    ],
)
def test_the_pack_finds_the_action_type_for_a_write(
    relation: str,
    transition: tuple[ValueClass, ValueClass],
    expected: str,
) -> None:
    found = LOADED_PACK.action_for(DEPOSIT_ACCOUNT.name, relation, transition)

    assert found is LOADED_PACK.action_types[expected]


@pytest.mark.parametrize(
    "transition",
    [(CLOSED, ACTIVE), (FROZEN, FROZEN), (ACTIVE, LifecycleStatus("locked"))],
    ids=["out of a terminal status", "to the same status", "to no move's"],
)
def test_the_pack_finds_no_action_type_for_a_move_it_lacks(
    transition: tuple[LifecycleStatus, LifecycleStatus],
) -> None:
    found = LOADED_PACK.action_for(
        DEPOSIT_ACCOUNT.name, "hasStatus", transition
    )

    assert found is None


def test_the_pack_finds_no_action_type_for_a_type_it_lacks() -> None:
    found = LOADED_PACK.action_for("LOAN", "hasStatus", (ACTIVE, FROZEN))

    assert found is None
