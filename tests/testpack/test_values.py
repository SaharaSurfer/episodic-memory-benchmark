from decimal import Decimal
from typing import Any

import pytest

from mbench.core.values.protocol import UniquenessScope
from tests.testpack.values import (
    DepositKind,
    InterestRate,
    LastFour,
    LifecycleStatus,
    MonetaryAmount,
    ProductName,
)
from tests.value_class_contract import (
    ClassCase,
    ContractCheck,
    checks_for,
    duplicate_tags,
)

# A float sneaks past the type checker only through Any.
FLOAT: Any = 26.4

CASES: list[ClassCase[Any]] = [
    ClassCase(
        InterestRate,
        valid=[
            InterestRate(Decimal("0")),
            InterestRate(Decimal("4.25")),
            InterestRate(Decimal("26.4")),
            InterestRate(Decimal("99.99")),
        ],
        invalid=[
            InterestRate(Decimal("4.255")),
            InterestRate(Decimal("-0.01")),
            InterestRate(Decimal("100")),
            InterestRate(Decimal("NaN")),
            InterestRate(FLOAT),
        ],
        equal_pairs=[
            (InterestRate(Decimal("26.4")), InterestRate(Decimal("26.40"))),
            (InterestRate(Decimal("0")), InterestRate(Decimal("0.00"))),
            # Trailing zeros add no precision, so this is not refused.
            (InterestRate(Decimal("4.250")), InterestRate(Decimal("4.25"))),
        ],
    ),
    ClassCase(
        MonetaryAmount,
        valid=[
            MonetaryAmount(Decimal("0")),
            MonetaryAmount(Decimal("5")),
            MonetaryAmount(Decimal("1234.56")),
            MonetaryAmount(Decimal("1234.5")),
        ],
        invalid=[
            MonetaryAmount(Decimal("1234.567")),
            MonetaryAmount(Decimal("-5")),
            MonetaryAmount(Decimal("Infinity")),
            MonetaryAmount(FLOAT),
        ],
        equal_pairs=[
            (MonetaryAmount(Decimal("5")), MonetaryAmount(Decimal("5.00"))),
            (MonetaryAmount(Decimal("-0")), MonetaryAmount(Decimal("0"))),
        ],
    ),
    ClassCase(
        LastFour,
        valid=[LastFour("4471"), LastFour("0000"), LastFour("4417")],
        invalid=[
            LastFour("447"),
            LastFour("44711"),
            LastFour("44a1"),
            LastFour("４４７１"),
        ],
        near_pairs=[
            (LastFour("4471"), LastFour("4472")),
            (LastFour("4471"), LastFour("9471")),
            (LastFour("4471"), LastFour("4417")),
            (LastFour("1234"), LastFour("2134")),
        ],
        far_pairs=[
            (LastFour("4471"), LastFour("4482")),
            (LastFour("1234"), LastFour("4231")),
            (LastFour("1234"), LastFour("1342")),
        ],
    ),
    ClassCase(
        DepositKind,
        valid=[DepositKind("checking"), DepositKind("savings")],
        invalid=[DepositKind("credit"), DepositKind("Checking")],
        far_pairs=[(DepositKind("checking"), DepositKind("savings"))],
    ),
    ClassCase(
        ProductName,
        valid=[ProductName("Everyday Checking"), ProductName("Goal Saver")],
        invalid=[ProductName("everyday checking"), ProductName("")],
    ),
    ClassCase(
        LifecycleStatus,
        valid=[LifecycleStatus(s) for s in sorted(LifecycleStatus.MEMBERS)],
        invalid=[LifecycleStatus("under review"), LifecycleStatus("")],
    ),
]


@pytest.mark.parametrize(
    ("case", "check"),
    [(case, check) for case in CASES for check in checks_for(case)],
    ids=[
        f"{case.cls.__name__}-{check.__name__}"
        for case in CASES
        for check in checks_for(case)
    ],
)
def test_each_class_honours_the_contract(
    case: ClassCase[Any], check: ContractCheck
) -> None:
    check(case)


def test_the_test_pack_tags_are_distinct() -> None:
    assert duplicate_tags([case.cls for case in CASES]) == []


def test_a_rate_and_an_amount_with_one_number_are_not_equal() -> None:
    amount: object = MonetaryAmount(Decimal("5.00"))

    assert InterestRate(Decimal("5.00")) != amount


def test_amounts_and_rates_render_as_the_dialogue_says_them() -> None:
    assert MonetaryAmount(Decimal("1234.5")).render() == "$1,234.50"
    assert InterestRate(Decimal("4.25")).render() == "4.25%"
    assert InterestRate(Decimal("26.4")).render() == "26.40%"
    assert LastFour("4471").render() == "ending 4471"
    assert LifecycleStatus("under_review").render() == "under review"


def test_last_four_near_zone_is_every_one_digit_change_and_swap() -> None:
    near = set(LastFour("4471").near())

    # 4 places × 9 other digits, plus the swaps 4-7 and 7-1
    # Swapping the two 4s changes nothing.
    assert len(near) == 4 * 9 + 2


def test_an_amount_too_long_to_hold_two_places_is_refused_not_raised() -> None:
    assert not MonetaryAmount(Decimal("1E+40")).is_valid()


def test_last_four_is_unique_in_the_scenario_and_others_have_no_scope() -> None:
    assert LastFour.scope is UniquenessScope.SCENARIO
    assert InterestRate.scope is UniquenessScope.NONE
