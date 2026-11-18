from dataclasses import dataclass
from typing import ClassVar

from mbench.core.values.protocol import ValueClass


@dataclass(frozen=True, eq=False)
class Contested:
    """What the world holds for a conflict: two values, neither of them true."""

    # Tells a conflict from a pack's values in the log.
    tag: ClassVar[str] = "contested"

    a: ValueClass
    b: ValueClass

    @property
    def members(self) -> frozenset[ValueClass]:
        """The two values, in no order, since neither comes first."""

        return frozenset({self.a, self.b})

    def __eq__(self, other: object) -> bool:
        """Whether the other is a conflict between the same two values."""

        return isinstance(other, Contested) and self.members == other.members

    def __hash__(self) -> int:
        """A hash that ignores the order of the two values."""

        return hash(self.members)


# Kept apart from ValueClass, so a command's plain value cannot be a conflict
# and a disclosure, which states one value, cannot carry one.
type WorldValue = ValueClass | Contested
