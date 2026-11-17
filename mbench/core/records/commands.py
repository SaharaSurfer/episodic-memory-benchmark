from collections.abc import Mapping
from dataclasses import dataclass

from mbench.core.records.ids import NodeId
from mbench.core.records.log import freeze
from mbench.core.values.protocol import ValueClass


@dataclass(frozen=True)
class InitCommand:
    """A request to create an entity, its values already filled."""

    session: int
    initiator: str
    action_type: str
    source: str
    writes: Mapping[str, ValueClass]

    def __post_init__(self) -> None:
        """Hold the writes read-only."""

        object.__setattr__(self, "writes", freeze(self.writes))


@dataclass(frozen=True)
class MutateCommand:
    """A request to write one value, its ActionType names the relation."""

    session: int
    initiator: str
    action_type: str
    source: str
    referent: NodeId
    # None for a status action, which fixes the status it writes.
    value: ValueClass | None = None


@dataclass(frozen=True)
class ReadCommand:
    """A request that a source state an entity's current values."""

    session: int
    initiator: str
    source: str
    entity: NodeId
