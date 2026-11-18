import random
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Protocol, cast

from mbench.core.values.protocol import DecimalValueClass, ValueClass


class MissingRead(LookupError):
    """A sampler reads a relation that holds no plain value."""


class PoolMembers(Protocol):
    """A pool as a draw reads it: only its members."""

    @property
    def members(self) -> Sequence[ValueClass]:
        """The values of the pool, in declared order."""
        ...


@dataclass(frozen=True)
class DrawContext:
    """What a draw may read, and the values it must not return."""

    pools: Mapping[str, PoolMembers] = field(default_factory=dict)
    values: Mapping[str, ValueClass] = field(default_factory=dict)
    current: ValueClass | None = None
    exclude: frozenset[ValueClass] = frozenset()


class Sampler[V: ValueClass](Protocol):
    """A block that draws one value from a seeded stream."""

    def draw(self, stream: random.Random, context: DrawContext) -> V | None:
        """A value not excluded, or None when nothing is left to draw."""
        ...


def draw[V: ValueClass](
    sampler: Sampler[V],
    stream: random.Random,
    *,
    pools: Mapping[str, PoolMembers] | None = None,
    values: Mapping[str, ValueClass] | None = None,
    exclude: Collection[ValueClass] = (),
) -> V | None:
    """Draw a first value, or None when every candidate is excluded."""

    context = DrawContext(
        pools=pools or {}, values=values or {}, exclude=frozenset(exclude)
    )
    return sampler.draw(stream, context)


def draw_step[V: ValueClass](
    sampler: Sampler[V],
    current: V,
    stream: random.Random,
    *,
    pools: Mapping[str, PoolMembers] | None = None,
    values: Mapping[str, ValueClass] | None = None,
    exclude: Collection[ValueClass] = (),
) -> V | None:
    """Draw the next value from the current one, never the current one."""

    # Every MUTATE changes the value it writes, so the current value is
    # always excluded, whatever the block.
    context = DrawContext(
        pools=pools or {},
        values=values or {},
        current=current,
        exclude=frozenset(exclude) | {current},
    )
    return sampler.draw(stream, context)


@dataclass(frozen=True)
class Choice[V: ValueClass]:
    """One of an inline list of values, or of a pool's members by its name."""

    options: Sequence[V] | str
    weights: Sequence[float] | None = None

    def draw(self, stream: random.Random, context: DrawContext) -> V | None:
        """A weighted pick among the options not excluded."""

        options = self._options(context)
        weights = self.weights or [1.0] * len(options)
        if len(weights) != len(options):
            raise ValueError(
                f"{len(weights)} weights for {len(options)} options"
            )

        free: list[V] = []
        free_weights: list[float] = []
        for option, weight in zip(options, weights, strict=True):
            # A zero weight is never drawn, so it counts as nothing left.
            if weight > 0 and option not in context.exclude:
                free.append(option)
                free_weights.append(weight)

        if not free:
            return None

        return stream.choices(free, weights=free_weights)[0]

    def _options(self, context: DrawContext) -> Sequence[V]:
        """The inline options, or the members of the named pool."""

        if not isinstance(self.options, str):
            return self.options

        pool = context.pools.get(self.options)
        if pool is None:
            raise LookupError(f"no pool named {self.options!r}")

        # The pack's load checks hold a pool to its samplers' class.
        return cast(Sequence[V], pool.members)


@dataclass(frozen=True)
class Range[D: DecimalValueClass]:
    """A value from low to high inclusive, on a grid of the given step."""

    cls: type[D]
    low: Decimal
    high: Decimal
    step: Decimal

    def __post_init__(self) -> None:
        """Refuse a range with no grid points."""

        if self.low > self.high:
            raise ValueError(f"low {self.low} is above high {self.high}")

    def draw(self, stream: random.Random, context: DrawContext) -> D | None:
        """A uniform pick among the grid points not excluded."""

        excluded = sorted(
            {i for i in map(self.index_of, context.exclude) if i is not None}
        )
        free = self.size() - len(excluded)
        if free <= 0:
            return None

        # The k-th free point, found by skipping the excluded ones below it.
        index = stream.randrange(free)
        for taken in excluded:
            if taken > index:
                break
            index += 1

        return self.at(index)

    def size(self) -> int:
        """How many grid points the range holds."""

        return int((self.high - self.low) // self.step) + 1

    def at(self, index: int) -> D:
        """The value at a grid point."""

        return self.cls(self.low + index * self.step)

    def index_of(self, value: ValueClass) -> int | None:
        """The grid point equal to the value, or None if none is."""

        payload = _decimal_payload(value)
        if payload is None:
            return None

        index, rest = divmod(payload - self.low, self.step)
        if rest != 0 or not 0 <= index < self.size():
            return None

        # Equality, not the payload alone, keeps out other classes.
        return int(index) if self.at(int(index)) == value else None


@dataclass(frozen=True)
class Step[D: DecimalValueClass]:
    """A move from the current value by a size from smallest to largest.

    Sizes are multiples of the range's step, and the move stays in the
    range, so a value at an end of it can only move inwards.
    """

    within: Range[D]
    smallest: Decimal
    largest: Decimal

    def draw(self, stream: random.Random, context: DrawContext) -> D | None:
        """A uniform pick among the reachable values not excluded."""

        current = (
            None
            if context.current is None
            else _decimal_payload(context.current)
        )
        if current is None:
            raise ValueError("a step needs the current value, a decimal")

        candidates = [
            value
            for value in self._reachable(current)
            if value not in context.exclude
        ]
        if not candidates:
            return None

        return stream.choice(candidates)

    def _reachable(self, current: Decimal) -> list[D]:
        """Every value one move away and in the range, in a fixed order."""

        reachable: list[D] = []
        size = self.smallest
        while size <= self.largest:
            for payload in (current - size, current + size):
                if self.within.low <= payload <= self.within.high:
                    reachable.append(self.within.cls(payload))
            size += self.within.step

        # A size of zero lands on the current value from both sides.
        return list(dict.fromkeys(reachable))


@dataclass(frozen=True)
class ByValue[V: ValueClass]:
    """A sampler chosen by the value an earlier relation holds."""

    relation: str
    branches: Mapping[ValueClass, Sampler[V]]

    def draw(self, stream: random.Random, context: DrawContext) -> V | None:
        """Draw with the branch for the value read."""

        read = context.values.get(self.relation)
        if read is None:
            raise MissingRead(f"reads {self.relation!r}, which has no value")

        branch = self.branches.get(read)
        if branch is None:
            raise LookupError(
                f"reads {self.relation!r} and has no branch for {read}"
            )

        return branch.draw(stream, context)


def _decimal_payload(value: ValueClass) -> Decimal | None:
    """The value's finite decimal payload, or None if it has none."""

    if not isinstance(value, DecimalValueClass):
        return None

    payload = value.payload
    if not isinstance(payload, Decimal) or not payload.is_finite():
        return None

    return payload
