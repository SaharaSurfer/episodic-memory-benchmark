from dataclasses import dataclass

from mbench.core.values.protocol import ValueClass


@dataclass(frozen=True)
class Pool[V: ValueClass]:
    """A list of values of one class, samplers name it by its key."""

    cls: type[V]
    members: tuple[V, ...]
