from decimal import Decimal

import pytest

from mbench.core.values.protocol import ValueClass
from tests.testpack.pack import DEPOSIT_ACCOUNT, LOADED_PACK, PAYMENT_CARD
from tests.testpack.values import (
    ACTIVE,
    CLOSED,
    FROZEN,
    INACTIVE,
    LOCKED,
    InterestRate,
    MonetaryAmount,
)

ACCOUNT = DEPOSIT_ACCOUNT.name
CARD = PAYMENT_CARD.name


@pytest.mark.parametrize(
    ("entity_type", "relation", "transition", "expected"),
    [
        (ACCOUNT, "hasStatus", (ACTIVE, FROZEN), "FREEZE_DEPOSIT_ACCOUNT"),
        (ACCOUNT, "hasStatus", (FROZEN, ACTIVE), "UNFREEZE_DEPOSIT_ACCOUNT"),
        (ACCOUNT, "hasStatus", (ACTIVE, CLOSED), "CLOSE_DEPOSIT_ACCOUNT"),
        (ACCOUNT, "hasStatus", (FROZEN, CLOSED), "CLOSE_DEPOSIT_ACCOUNT"),
        (CARD, "hasStatus", (INACTIVE, ACTIVE), "ACTIVATE_CARD"),
        (CARD, "hasStatus", (ACTIVE, LOCKED), "LOCK_CARD"),
        (CARD, "hasStatus", (LOCKED, ACTIVE), "UNLOCK_CARD"),
        (CARD, "hasStatus", (INACTIVE, CLOSED), "CLOSE_CARD"),
        (CARD, "hasStatus", (ACTIVE, CLOSED), "CLOSE_CARD"),
        (CARD, "hasStatus", (LOCKED, CLOSED), "CLOSE_CARD"),
        (
            ACCOUNT,
            "hasInterestRate",
            (InterestRate(Decimal("4.25")), InterestRate(Decimal("3.90"))),
            "REPRICE_DEPOSIT_ACCOUNT",
        ),
        (
            ACCOUNT,
            "hasMonthlyFee",
            (MonetaryAmount(Decimal("5")), MonetaryAmount(Decimal("0"))),
            "CHANGE_ACCOUNT_FEE",
        ),
    ],
)
def test_the_pack_finds_the_action_type_for_a_write(
    entity_type: str,
    relation: str,
    transition: tuple[ValueClass, ValueClass],
    expected: str,
) -> None:
    found = LOADED_PACK.action_for(entity_type, relation, transition)

    assert found is LOADED_PACK.action_types[expected]


@pytest.mark.parametrize(
    ("entity_type", "transition"),
    [
        (ACCOUNT, (CLOSED, ACTIVE)),
        (ACCOUNT, (FROZEN, FROZEN)),
        (ACCOUNT, (ACTIVE, LOCKED)),
        (CARD, (INACTIVE, LOCKED)),
        (CARD, (CLOSED, ACTIVE)),
    ],
    ids=[
        "out of a terminal status",
        "to the same status",
        "to no move's",
        "locking an inactive card",
        "out of a closed card",
    ],
)
def test_the_pack_finds_no_action_type_for_a_move_it_lacks(
    entity_type: str, transition: tuple[ValueClass, ValueClass]
) -> None:
    found = LOADED_PACK.action_for(entity_type, "hasStatus", transition)

    assert found is None


def test_the_pack_finds_no_action_type_for_a_type_it_lacks() -> None:
    found = LOADED_PACK.action_for("LOAN", "hasStatus", (ACTIVE, FROZEN))

    assert found is None
