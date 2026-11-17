from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from mbench.core.records.ids import NodeId
from mbench.core.records.log import (
    Event,
    InitEvent,
    MutateEvent,
    Record,
    freeze,
)
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

    if isinstance(event, InitEvent):
        entry = _created(event, pack)
    else:
        entry = _mutated(registry._entries[event.referent], event)

    return Registry(freeze({**registry._entries, entry.id: entry}))


def _created(event: InitEvent, pack: LoadedPack) -> Entry:
    """The entry an INIT creates, every value stamped with its session."""

    entity_type = pack.action_types[event.action_type].referent_type

    return Entry(entity_type, event.new_id, _stamped(event))


def _mutated(entry: Entry, event: MutateEvent) -> Entry:
    """The entry with the MUTATE's value written and stamped."""

    return Entry(entry.type, entry.id, {**entry.values, **_stamped(event)})


def _stamped(event: Event) -> dict[str, Stamped]:
    """Each value the event writes, stamped with its session."""

    return {
        relation: Stamped(value, event.session)
        for relation, value in event.writes.items()
    }


def fold_world(
    records: Iterable[Record],
    pack: LoadedPack,
    start: Registry | None = None,
) -> Registry:
    """The registry after the log's events, from the given or empty state."""

    registry = Registry() if start is None else start

    for record in records:
        if isinstance(record, InitEvent | MutateEvent):
            registry = evolve_world(registry, record, pack)

    return registry
