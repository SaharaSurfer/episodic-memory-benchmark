from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from mbench.core.records.ids import NodeId
from mbench.core.records.log import Event, InitEvent, Record, freeze
from mbench.core.values.protocol import ValueClass
from mbench.packs.spec import LoadedPack


@dataclass(frozen=True)
class Stamped:
    """A current value and the session that last wrote it."""

    value: ValueClass
    session: int


@dataclass(frozen=True)
class Entry:
    """One entity as the world holds it now: type, id, current values."""

    type: str
    id: NodeId
    values: Mapping[str, Stamped]

    def __post_init__(self) -> None:
        """Hold the values read-only."""

        object.__setattr__(self, "values", freeze(self.values))


@dataclass(frozen=True)
class Registry:
    """The world's state at a position of the log, one entry per entity."""

    _entries: Mapping[NodeId, Entry] = field(default_factory=lambda: freeze({}))

    def ids(self) -> frozenset[NodeId]:
        """The id of every entity, terminal ones included."""

        return frozenset(self._entries)

    def entry(self, entity: NodeId) -> Entry | None:
        """The entity's entry, or None if no such entity exists."""

        return self._entries.get(entity)


def evolve_world(
    registry: Registry, event: Event, pack: LoadedPack
) -> Registry:
    """The registry after one event."""

    entity_type = pack.action_types[event.action_type].creates
    values = {
        relation: Stamped(value, event.session)
        for relation, value in event.writes.items()
    }
    entry = Entry(entity_type, event.new_id, values)

    return Registry(freeze({**registry._entries, event.new_id: entry}))


def fold_world(
    records: Iterable[Record],
    pack: LoadedPack,
    start: Registry | None = None,
) -> Registry:
    """The registry after the log's events, from the given or empty state."""

    registry = Registry() if start is None else start

    for record in records:
        if isinstance(record, InitEvent):
            registry = evolve_world(registry, record, pack)

    return registry
