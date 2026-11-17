from collections.abc import Iterator
from enum import Enum
from typing import ClassVar, Protocol, Self, runtime_checkable


class UniquenessScope(Enum):
    """Where no two values of an identifier class may be equal."""

    NONE = "none"
    SCENARIO = "scenario"
    TYPE = "type"


class Zone(Enum):
    """How alike two values are: indistinguishable, lookalikes, or neither."""

    SAME = "same"
    NEAR = "near"
    FAR = "far"


class ValueClass(Protocol):
    """
    What a pack's value class provides.

    Equality is canonical: two values are equal iff they are the same
    value of the same class, so `==` and `hash` serve scoring and
    uniqueness as they are. A value may be built from any payload, it
    may store an equal payload in canonical form, but never turns an
    invalid payload valid, so an invalid value can be written and refused.
    """

    # Tells classes apart in the log, unique across a pack's classes.
    tag: ClassVar[str]
    scope: ClassVar[UniquenessScope] = UniquenessScope.NONE

    def is_valid(self) -> bool:
        """Whether the payload meets the class invariant."""
        ...

    def render(self) -> str:
        """The exact string the dialogue says for this value."""
        ...


@runtime_checkable
class ZonedValueClass(ValueClass, Protocol):
    """A value class with same / near / far zones and a near generator."""

    def zone(self, other: Self) -> Zone:
        """The zone `other` falls in, seen from this value."""
        ...

    def near(self) -> Iterator[Self]:
        """Every valid value in this value's near zone, never itself."""
        ...
