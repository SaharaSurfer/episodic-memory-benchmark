from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from mbench.core.values.samplers import ByValue, Choice, Range, Sampler, Step
from tests.testpack.values import (
    DepositKind,
    InterestRate,
    LastFour,
    MonetaryAmount,
    ProductName,
)

CHECKING = DepositKind("checking")
SAVINGS = DepositKind("savings")

CHECKING_RATES = Range(
    InterestRate, Decimal("0.00"), Decimal("0.50"), Decimal("0.01")
)
SAVINGS_RATES = Range(
    InterestRate, Decimal("0.01"), Decimal("4.50"), Decimal("0.01")
)
MONTHLY_FEES = Choice(
    tuple(MonetaryAmount(Decimal(fee)) for fee in ("0", "5", "10", "12", "15"))
)
# Four digits as a string are not a decimal, so a list stands in for a range.
ANY_LAST_FOUR = Choice(tuple(LastFour(f"{n:04}") for n in range(10_000)))

# First values, keyed by (INIT, relation), drawn in this order: an INIT's
# kind comes first so the samplers after it can read it.
INIT_SAMPLERS: Mapping[tuple[str, str], Sampler[Any]] = {
    ("OPEN_DEPOSIT_ACCOUNT", "kind"): Choice(
        (CHECKING, SAVINGS), weights=(0.6, 0.4)
    ),
    ("OPEN_DEPOSIT_ACCOUNT", "lastFour"): ANY_LAST_FOUR,
    ("OPEN_DEPOSIT_ACCOUNT", "productName"): ByValue[ProductName](
        "kind",
        {
            CHECKING: Choice("checking_products"),
            SAVINGS: Choice("savings_products"),
        },
    ),
    ("OPEN_DEPOSIT_ACCOUNT", "hasInterestRate"): ByValue(
        "kind", {CHECKING: CHECKING_RATES, SAVINGS: SAVINGS_RATES}
    ),
    ("OPEN_DEPOSIT_ACCOUNT", "hasMonthlyFee"): MONTHLY_FEES,
}

# Next values, keyed by (entity type, relation)
STEP_SAMPLERS: Mapping[tuple[str, str], Sampler[Any]] = {
    ("DEPOSIT_ACCOUNT", "hasInterestRate"): ByValue(
        "kind",
        {
            CHECKING: Step(CHECKING_RATES, Decimal("0.05"), Decimal("0.50")),
            SAVINGS: Step(SAVINGS_RATES, Decimal("0.05"), Decimal("0.50")),
        },
    ),
    ("DEPOSIT_ACCOUNT", "hasMonthlyFee"): MONTHLY_FEES,
}
