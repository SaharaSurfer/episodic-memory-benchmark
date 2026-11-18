from collections.abc import Mapping
from dataclasses import dataclass, field

from mbench.core.records.frozen import freeze
from mbench.core.records.ids import NodeId
from mbench.core.values.protocol import ValueClass


@dataclass(frozen=True)
class InitCommand:
    """A request to create an entity, its values already filled."""

    session: int
    initiator: str
    action_type: str
    writes: Mapping[str, ValueClass]
    # None leaves the source of its disclosures to the default.
    source: str | None = None
    links: Mapping[str, NodeId] = field(default_factory=lambda: freeze({}))
    # The name of the pack's role filter per link endpoint, beside the
    # ActionType's gate: which entity may be picked, not what the action allows.
    filters: Mapping[str, str] = field(default_factory=lambda: freeze({}))

    def __post_init__(self) -> None:
        """Hold the writes, links and filters read-only."""

        object.__setattr__(self, "writes", freeze(self.writes))
        object.__setattr__(self, "links", freeze(self.links))
        object.__setattr__(self, "filters", freeze(self.filters))


@dataclass(frozen=True)
class MutateCommand:
    """A request to write one value, its ActionType names the relation."""

    session: int
    initiator: str
    action_type: str
    referent: NodeId
    # None for a status action, which fixes the status it writes.
    value: ValueClass | None = None
    # None leaves the source of its disclosure to the default.
    source: str | None = None


@dataclass(frozen=True)
class ReadCommand:
    """A request that a source state an entity's current values."""

    session: int
    initiator: str
    source: str
    entity: NodeId


type EventCommand = InitCommand | MutateCommand
type Command = EventCommand | ReadCommand
