from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from enum import Enum

from mbench.core.records.frozen import freeze
from mbench.core.records.ids import NodeId
from mbench.core.records.log import (
    Event,
    InitEvent,
    MutateEvent,
    Record,
)
from mbench.core.values.contested import Contested, WorldValue
from mbench.core.values.protocol import ValueClass
from mbench.packs.spec import LoadedPack


@dataclass(frozen=True)
class Stamped:
    """A current value and the session that last wrote it."""

    value: WorldValue
    session: int


@dataclass(frozen=True)
class Entry:
    """One entity as the world holds it now: type, id, values and links."""

    type: str
    id: NodeId
    values: Mapping[str, Stamped]
    # The entity each structural link points at, fixed since the INIT.
    links: Mapping[str, NodeId] = field(default_factory=lambda: freeze({}))

    def __post_init__(self) -> None:
        """Hold the values and links read-only."""

        object.__setattr__(self, "values", freeze(self.values))
        object.__setattr__(self, "links", freeze(self.links))


@dataclass(frozen=True)
class Registry:
    """The world's state at a position of the log, one entry per entity."""

    _entries: Mapping[NodeId, Entry] = field(default_factory=lambda: freeze({}))

    def ids(self) -> frozenset[NodeId]:
        """The id of every entity, terminal ones included."""

        return frozenset(self._entries)

    def entries(self) -> tuple[Entry, ...]:
        """Every entity's entry, terminal ones included."""

        return tuple(self._entries.values())

    def entry(self, entity: NodeId) -> Entry | None:
        """The entity's entry, or None if no such entity exists."""

        return self._entries.get(entity)


class Liveness(Enum):
    """Whether an entity's status leaves it in the world's play."""

    LIVE = "live"
    TERMINAL = "terminal"
    # A contested status has no true value, so neither answer can be read.
    UNDECIDED = "undecided"


def liveness(entry: Entry, pack: LoadedPack) -> Liveness:
    """Whether the entity's status is non-terminal, terminal or contested."""

    entity_type = pack.entity_types[entry.type]
    if entity_type.status is None:
        return Liveness.LIVE

    status = entry.values[entity_type.status].value
    if isinstance(status, Contested):
        return Liveness.UNDECIDED

    return (
        Liveness.TERMINAL if status in entity_type.terminal else Liveness.LIVE
    )


def true_value(entry: Entry, relation: str) -> ValueClass | None:
    """The pair's value, or None if the relation is absent or contested."""

    current = entry.values.get(relation)
    if current is None or isinstance(current.value, Contested):
        return None

    return current.value


def true_values(entry: Entry) -> dict[str, ValueClass]:
    """Every relation's value, leaving out the contested ones."""

    return {
        relation: stamped.value
        for relation, stamped in entry.values.items()
        if not isinstance(stamped.value, Contested)
    }


def held_values(entry: Entry, relation: str) -> frozenset[ValueClass]:
    """The values the pair holds: both sides of a conflict, or its one value."""

    current = entry.values.get(relation)
    if current is None:
        return frozenset()
    if isinstance(current.value, Contested):
        return current.value.members

    return frozenset({current.value})


def contested_relations(entry: Entry) -> frozenset[str]:
    """The relations whose pair holds a conflict."""

    return frozenset(
        relation
        for relation, stamped in entry.values.items()
        if isinstance(stamped.value, Contested)
    )


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

    return Entry(entity_type, event.new_id, _stamped(event), event.links)


def _mutated(entry: Entry, event: MutateEvent) -> Entry:
    """The entry with the MUTATE's value written and stamped."""

    return replace(entry, values={**entry.values, **_stamped(event)})


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
