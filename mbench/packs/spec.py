from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType

from mbench.core.values.protocol import ValueClass

type Gate = Mapping[str, frozenset[ValueClass]]
type Transition = tuple[ValueClass, ValueClass]


def _frozen_gate(gate: Gate) -> Gate:
    """A read-only copy of the gate, each admitted set a frozen set."""

    return MappingProxyType(
        {relation: frozenset(admitted) for relation, admitted in gate.items()}
    )


def _frozen_gates(gates: Mapping[str, Gate]) -> Mapping[str, Gate]:
    """A read-only copy of a gate per key, each gate frozen too."""

    return MappingProxyType(
        {key: _frozen_gate(gate) for key, gate in gates.items()}
    )


@dataclass(frozen=True)
class Pool[V: ValueClass]:
    """A list of values of one class, samplers name it by its key."""

    cls: type[V]
    members: tuple[V, ...]


@dataclass(frozen=True)
class EntityType:
    """A type of entity, its relations' classes and its terminal statuses."""

    name: str
    relations: Mapping[str, type[ValueClass]]
    # The relation holding the status, a type without one is
    # live once it exists.
    status: str | None = None
    terminal: frozenset[ValueClass] = frozenset()
    # Per link, the types it may point at: one target, set by the INIT.
    links: Mapping[str, frozenset[str]] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def __post_init__(self) -> None:
        """Hold the relations and links read-only, the terminals as a set."""

        object.__setattr__(
            self, "relations", MappingProxyType(dict(self.relations))
        )
        object.__setattr__(self, "terminal", frozenset(self.terminal))
        object.__setattr__(
            self,
            "links",
            MappingProxyType(
                {link: frozenset(types) for link, types in self.links.items()}
            ),
        )


@dataclass(frozen=True)
class InitAction:
    """An ActionType that creates an entity of its referent type."""

    name: str
    referent_type: str
    # The links the INIT writes, each with the gate its endpoint must pass.
    links: Mapping[str, Gate] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def __post_init__(self) -> None:
        """Hold the links and their gates read-only."""

        object.__setattr__(self, "links", _frozen_gates(self.links))


@dataclass(frozen=True)
class MutateAction:
    """An ActionType that writes one relation of an entity of its type."""

    name: str
    referent_type: str
    relation: str
    # The values the referent must hold, per relation, to take the action.
    gate: Gate = field(default_factory=lambda: MappingProxyType({}))
    # A status action writes the status it fixes, so its command names none,
    # and its gate is its source statuses.
    fixes: ValueClass | None = None

    def __post_init__(self) -> None:
        """Hold the gate read-only."""

        object.__setattr__(self, "gate", _frozen_gate(self.gate))

    def takes(self, transition: Transition) -> bool:
        """Whether the action can make this change to the relation it writes."""

        before, after = transition
        admitted = self.gate.get(self.relation)

        return (admitted is None or before in admitted) and (
            self.fixes is None or self.fixes == after
        )


type ActionType = InitAction | MutateAction


@dataclass(frozen=True)
class Actor:
    """A party that initiates events, on stage or off."""

    name: str


@dataclass(frozen=True)
class Speaker:
    """A party that talks, speaking for the actor it represents."""

    id: str
    represents: str


class SourceKind(Enum):
    """Whether a source is a speaker talking or a document quoted."""

    SPEAKER = "speaker"
    DOCUMENT = "document"


@dataclass(frozen=True)
class Source:
    """Who a disclosure is attributed to: a speaker, or a document."""

    id: str
    # Declared, not derived from the speakers, so a speaker source left
    # without its speaker is caught rather than read as a document.
    kind: SourceKind
    # Read only for ties: a conflict's two sources have equal authority.
    authority: int


@dataclass(frozen=True)
class LoadedPack:
    """What the core reads of a pack: its types, ActionTypes and dialogue."""

    entity_types: Mapping[str, EntityType]
    action_types: Mapping[str, ActionType]
    actors: Mapping[str, Actor]
    speakers: Mapping[str, Speaker]
    # In declaration order, which decides the document a default falls to.
    sources: Mapping[str, Source]
    # The actor whose world this is.
    owner: str

    def __post_init__(self) -> None:
        """Hold every table read-only, and refuse unmatched speaker sources."""

        for table in (
            "entity_types",
            "action_types",
            "actors",
            "speakers",
            "sources",
        ):
            object.__setattr__(
                self, table, MappingProxyType(dict(getattr(self, table)))
            )

        # A speaker's disclosures cite its source, so each needs the other.
        speaking = {
            id
            for id, source in self.sources.items()
            if source.kind is SourceKind.SPEAKER
        }
        unmatched = speaking ^ set(self.speakers)
        if unmatched:
            raise ValueError(
                f"speakers and speaker sources differ: {sorted(unmatched)}"
            )

    def action_for(
        self, entity_type: str, relation: str, transition: Transition
    ) -> MutateAction | None:
        """The ActionType that makes this write on this type, if one does."""

        for action in self.action_types.values():
            if (
                isinstance(action, MutateAction)
                and action.referent_type == entity_type
                and action.relation == relation
                and action.takes(transition)
            ):
                return action

        return None
