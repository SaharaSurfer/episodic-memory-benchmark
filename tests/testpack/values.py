import re
from collections.abc import Iterator
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import ClassVar, Self

from mbench.core.values.protocol import (
    UniquenessScope,
    ValueClass,
    Zone,
    ZonedValueClass,
)

CENT = Decimal("0.01")
FOUR_DIGITS = re.compile(r"[0-9]{4}")

CHECKING_PRODUCTS = (
    "Everyday Checking",
    "Premier Checking",
    "Student Checking",
    "Basic Checking",
)
SAVINGS_PRODUCTS = (
    "High Yield Savings",
    "Everyday Savings",
    "Goal Saver",
    "Money Market Savings",
)


def _two_places(payload: Decimal) -> Decimal:
    """The payload held to two places, if it fits in two, else as given."""

    if not (isinstance(payload, Decimal) and payload.is_finite()):
        return payload

    try:
        held = payload.quantize(CENT)
    except InvalidOperation:
        # Too many digits to hold two places, validation refuses it.
        return payload

    # Only an exact fit is rescaled, so a more precise value stays
    # invalid instead of being rounded into a valid one.
    if held != payload:
        return payload

    return held.copy_abs() if held.is_zero() else held


@dataclass(frozen=True)
class _TwoPlaceDecimal(ValueClass):
    """A decimal stored to exactly two places, so 26.4 and 26.40 are one."""

    payload: Decimal

    def __post_init__(self) -> None:
        """Store the payload to two places where it fits in two."""

        object.__setattr__(self, "payload", _two_places(self.payload))

    def _holds_two_places(self) -> bool:
        """Whether the payload is a finite decimal with exactly two places."""

        return (
            isinstance(self.payload, Decimal)
            and self.payload.is_finite()
            and self.payload.as_tuple().exponent == -2
        )


@dataclass(frozen=True)
class MonetaryAmount(_TwoPlaceDecimal):
    """Dollars and cents, never negative."""

    tag: ClassVar[str] = "monetary_amount"

    def is_valid(self) -> bool:
        """A two-place decimal of at least zero."""

        return self._holds_two_places() and self.payload >= 0

    def render(self) -> str:
        """Dollars with thousands separators, as "$1,234.56"."""

        return f"${self.payload:,}"


@dataclass(frozen=True)
class InterestRate(_TwoPlaceDecimal):
    """A percentage under 100 points."""

    tag: ClassVar[str] = "interest_rate"

    def is_valid(self) -> bool:
        """A two-place decimal from 0 up to, not including, 100."""

        return self._holds_two_places() and 0 <= self.payload < 100

    def render(self) -> str:
        """The percentage, as "4.25%"."""

        return f"{self.payload}%"


@dataclass(frozen=True)
class LastFour(ZonedValueClass):
    """The last four digits of an account or card number."""

    tag: ClassVar[str] = "last_four"
    scope: ClassVar[UniquenessScope] = UniquenessScope.SCENARIO
    payload: str

    def is_valid(self) -> bool:
        """Exactly four ASCII digits."""

        return FOUR_DIGITS.fullmatch(self.payload) is not None

    def render(self) -> str:
        """As the dialogue says it: "ending 4471"."""

        return f"ending {self.payload}"

    def zone(self, other: Self) -> Zone:
        """Same if equal, near if a lookalike, far otherwise."""

        if other == self:
            return Zone.SAME

        if other.payload in _digit_lookalikes(self.payload):
            return Zone.NEAR

        return Zone.FAR

    def near(self) -> Iterator[Self]:
        """Every lookalike of these four digits."""

        for payload in sorted(_digit_lookalikes(self.payload)):
            yield type(self)(payload)


def _digit_lookalikes(digits: str) -> set[str]:
    """Strings with one digit changed or two neighbours swapped."""

    lookalikes: set[str] = set()

    for i, digit in enumerate(digits):
        for other in "0123456789":
            if other != digit:
                lookalikes.add(digits[:i] + other + digits[i + 1 :])

    for i in range(len(digits) - 1):
        swapped = digits[:i] + digits[i + 1] + digits[i] + digits[i + 2 :]
        if swapped != digits:
            lookalikes.add(swapped)

    return lookalikes


@dataclass(frozen=True)
class DepositKind(ZonedValueClass):
    """Whether a deposit account is checking or savings."""

    tag: ClassVar[str] = "deposit_kind"
    MEMBERS: ClassVar[frozenset[str]] = frozenset({"checking", "savings"})
    payload: str

    def is_valid(self) -> bool:
        """One of the two kinds."""

        return self.payload in self.MEMBERS

    def render(self) -> str:
        """The kind as a word."""

        return self.payload

    def zone(self, other: Self) -> Zone:
        """Same if equal, far otherwise: no kind looks like another."""

        return Zone.SAME if other == self else Zone.FAR

    def near(self) -> Iterator[Self]:
        """Nothing: the near zone is empty."""

        yield from ()


@dataclass(frozen=True)
class ProductName(ValueClass):
    """The name of an account's product, from the pack's product lists."""

    tag: ClassVar[str] = "product_name"
    MEMBERS: ClassVar[frozenset[str]] = frozenset(
        CHECKING_PRODUCTS + SAVINGS_PRODUCTS
    )
    payload: str

    def is_valid(self) -> bool:
        """A listed product name, spelled exactly as listed."""

        return self.payload in self.MEMBERS

    def render(self) -> str:
        """The name as spelled."""

        return self.payload


@dataclass(frozen=True)
class LifecycleStatus(ValueClass):
    """Where an entity is in its life, every type's statuses are here."""

    tag: ClassVar[str] = "lifecycle_status"
    MEMBERS: ClassVar[frozenset[str]] = frozenset(
        {
            "active",
            "frozen",
            "closed",
            "inactive",
            "locked",
            "scheduled",
            "pending",
            "posted",
            "reversed",
            "cancelled",
            "open",
            "under_review",
            "approved",
            "denied",
        }
    )
    payload: str

    def is_valid(self) -> bool:
        """One of the statuses."""

        return self.payload in self.MEMBERS

    def render(self) -> str:
        """The status as words: "under review"."""

        return self.payload.replace("_", " ")
