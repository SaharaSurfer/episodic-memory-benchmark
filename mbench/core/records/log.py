import datetime
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from mbench.core.records.ids import NodeId
from mbench.core.values.protocol import ValueClass

# The action type of a disclosure that re-states current values, stated by no
# event and so named by the core rather than by a pack's ActionTypes.
READ = "READ"


def freeze[K, V](mapping: Mapping[K, V]) -> Mapping[K, V]:
    """A read-only copy, so later changes to the given map don't reach it."""

    return MappingProxyType(dict(mapping))


@dataclass(frozen=True)
class InitEvent:
    """An event that creates an entity and writes its first values."""

    session: int
    initiator: str
    action_type: str
    new_id: NodeId
    writes: Mapping[str, ValueClass]

    def __post_init__(self) -> None:
        """Hold the writes read-only."""

        object.__setattr__(self, "writes", freeze(self.writes))


@dataclass(frozen=True)
class MutateEvent:
    """An event that writes one value of an existing entity."""

    session: int
    initiator: str
    action_type: str
    referent: NodeId
    writes: Mapping[str, ValueClass]

    def __post_init__(self) -> None:
        """Hold the one write read-only, refusing any other number of them."""

        if len(self.writes) != 1:
            raise ValueError(
                f"a MUTATE writes one value, not {len(self.writes)}"
            )

        object.__setattr__(self, "writes", freeze(self.writes))


@dataclass(frozen=True)
class Disclosure:
    """A source stating one value of one entity's relation in a session."""

    session: int
    source: str
    action_type: str
    initiator: str
    entity: NodeId
    relation: str
    value: ValueClass
    node_id: NodeId


type Event = InitEvent | MutateEvent
type Record = Event | Disclosure


@dataclass(frozen=True)
class SessionRow:
    """One session's row of the table, tier and date are filled later."""

    index: int
    tier: str | None = None
    date: datetime.date | None = None


@dataclass(frozen=True)
class Log:
    """The records in order, and the sessions they name by index."""

    records: tuple[Record, ...] = ()
    sessions: Mapping[int, SessionRow] = field(
        default_factory=lambda: freeze({})
    )

    def __post_init__(self) -> None:
        """Hold the session table read-only."""

        object.__setattr__(self, "sessions", freeze(self.sessions))

    def append(self, records: Iterable[Record]) -> "Log":
        """A new log with the records added and a row for each new session."""

        added = tuple(records)
        sessions = dict(self.sessions)

        for record in added:
            sessions.setdefault(record.session, SessionRow(record.session))

        return Log(self.records + added, sessions)
