import datetime
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from itertools import chain

from mbench.core.records.commands import Command
from mbench.core.records.frozen import freeze
from mbench.core.records.ids import NodeId
from mbench.core.values.protocol import ValueClass

# The action type of a disclosure that re-states current values, stated by no
# event and so named by the core rather than by a pack's ActionTypes.
READ = "READ"


@dataclass(frozen=True)
class Link:
    """What a structural link's disclosure states: the entity it points at."""

    target: NodeId


@dataclass(frozen=True)
class InitEvent:
    """An event that creates an entity, writing its first values and links."""

    session: int
    initiator: str
    action_type: str
    new_id: NodeId
    writes: Mapping[str, ValueClass]
    # The entity each structural link points at, written here and never again.
    links: Mapping[str, NodeId] = field(default_factory=lambda: freeze({}))

    def __post_init__(self) -> None:
        """Hold the writes and links read-only."""

        object.__setattr__(self, "writes", freeze(self.writes))
        object.__setattr__(self, "links", freeze(self.links))


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
    value: ValueClass | Link
    # Unused for a link, which makes an edge, not a value node.
    node_id: NodeId


type Event = InitEvent | MutateEvent
type Record = Event | Disclosure


@dataclass(frozen=True)
class AcceptedCommand:
    """A command the predicate accepted, with the records it produced."""

    command: Command
    records: tuple[Record, ...]


@dataclass(frozen=True)
class SessionRow:
    """One session's row of the table, tier and date are filled later."""

    index: int
    tier: str | None = None
    date: datetime.date | None = None


@dataclass(frozen=True)
class Log:
    """The accepted commands in order, and the sessions named by index."""

    accepted: tuple[AcceptedCommand, ...] = ()
    sessions: Mapping[int, SessionRow] = field(
        default_factory=lambda: freeze({})
    )

    def __post_init__(self) -> None:
        """Hold the session table read-only."""

        object.__setattr__(self, "sessions", freeze(self.sessions))

    @property
    def records(self) -> tuple[Record, ...]:
        """Every accepted command's records, in order."""

        return tuple(
            chain.from_iterable(accepted.records for accepted in self.accepted)
        )

    def append(self, accepted: Iterable[AcceptedCommand]) -> "Log":
        """A new log with the commands added and a row per new session."""

        added = tuple(accepted)
        sessions = dict(self.sessions)

        # Rows come from records, so a command that produced none adds none.
        for accepted_command in added:
            for record in accepted_command.records:
                sessions.setdefault(record.session, SessionRow(record.session))

        return Log(self.accepted + added, sessions)
