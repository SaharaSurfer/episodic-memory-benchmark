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


def _has_zones(cls: type[ValueClass]) -> bool:
    """Whether the class gives zones and a near generator."""

    # Not `issubclass` with ZonedValueClass: a protocol with data members,
    # as its class tag, cannot be checked against a class.
    return all(callable(getattr(cls, name, None)) for name in ("zone", "near"))


@dataclass(frozen=True)
class Pool[V: ValueClass]:
    """A list of values of one class, samplers name it by its key."""

    cls: type[V]
    members: tuple[V, ...]


@dataclass(frozen=True)
class EntityType:
    """A type of entity: its relations, anchor and terminal statuses."""

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
    # The relations said to name an entity in words, no two entities of the
    # type may hold them all in one same zone. Empty for a type never named.
    anchor: tuple[str, ...] = ()
    # Whether a question may name an entity of the type, apart from anchoring
    # it: a type may be anchored so a hop can mention it, yet never named.
    nameable: bool = False

    def __post_init__(self) -> None:
        """Hold the tables read-only, and refuse an anchor it cannot check."""

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

        strays = set(self.anchor) - self.relations.keys()
        if strays:
            raise ValueError(
                f"{self.name} anchors on relations it lacks: {sorted(strays)}"
            )

        # A named entity's anchor must tell lookalikes from one entity, which
        # takes zones. A type never named compares its anchor by equality.
        unzoned = [
            part
            for part in self.anchor
            if self.nameable and not _has_zones(self.relations[part])
        ]
        if unzoned:
            raise ValueError(
                f"{self.name} is nameable, but its anchor parts {unzoned}"
                " have no zones"
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
class Framing:
    """One way an ActionType occurs: who starts it and who states it."""

    initiator: str
    source: str


@dataclass(frozen=True)
class Linker:
    """Entities of a type that point at another entity by a link."""

    entity_type: str
    link: str


@dataclass(frozen=True)
class RoleFilter:
    """A named condition on which entity of a type a role may bind."""

    name: str
    entity_type: str
    # The values the entity must hold, per relation.
    values: Gate = field(default_factory=lambda: MappingProxyType({}))
    # Whether the entity's current status must be non-terminal.
    live: bool = False
    # The entity must have no live entity pointing at it in any of these ways.
    no_live_linkers: tuple[Linker, ...] = ()

    def __post_init__(self) -> None:
        """Hold the required values read-only."""

        object.__setattr__(self, "values", _frozen_gate(self.values))


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
    role_filters: Mapping[str, RoleFilter] = field(
        default_factory=lambda: MappingProxyType({})
    )
    # Per ActionType name, every way the pack has it occur.
    framings: Mapping[str, tuple[Framing, ...]] = field(
        default_factory=lambda: MappingProxyType({})
    )
    # Per entity type, the relations an INIT's derivations read of it.
    derivation_reads: Mapping[str, frozenset[str]] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def __post_init__(self) -> None:
        """Hold every table read-only, and refuse names that do not match."""

        for table in (
            "entity_types",
            "action_types",
            "actors",
            "speakers",
            "sources",
            "role_filters",
            "framings",
            "derivation_reads",
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

        # A misspelt name would read as an action nobody can contest, and
        # conflicts on it would be refused with no sign of the mistake.
        framings = [
            framing for group in self.framings.values() for framing in group
        ]
        unknown = (
            (self.framings.keys() - self.action_types.keys())
            | ({framing.initiator for framing in framings} - self.actors.keys())
            | ({framing.source for framing in framings} - self.sources.keys())
        )
        if unknown:
            raise ValueError(f"framings name undeclared {sorted(unknown)}")

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

    def passes_owner_rule(self, action: str) -> bool:
        """Whether someone other than the owner's speaker states the action."""

        return bool(self._contestable_initiators(action))

    def shared_initiators(self, first: str, second: str) -> frozenset[str]:
        """The initiators both actions have a contestable framing for."""

        return self._contestable_initiators(
            first
        ) & self._contestable_initiators(second)

    def _contestable_initiators(self, action: str) -> frozenset[str]:
        """The initiators of the action's framings the owner does not state."""

        # The owner can't be unsure of a change it stated itself.
        owners_speakers = {
            speaker.id
            for speaker in self.speakers.values()
            if speaker.represents == self.owner
        }

        return frozenset(
            framing.initiator
            for framing in self.framings.get(action, ())
            if framing.source not in owners_speakers
        )

    def relations_read(self, name: str) -> Mapping[str, frozenset[str]]:
        """The relations, per entity type, that the named filter reads."""

        role_filter = self.role_filters[name]
        reads = {role_filter.entity_type: set(role_filter.values)}

        if role_filter.live:
            reads[role_filter.entity_type] |= self._status_relations(
                role_filter.entity_type
            )
        for linker in role_filter.no_live_linkers:
            reads.setdefault(linker.entity_type, set()).update(
                {linker.link} | self._status_relations(linker.entity_type)
            )

        return {
            entity_type: frozenset(relations)
            for entity_type, relations in reads.items()
        }

    def relations_legality_reads(self, entity_type: str) -> frozenset[str]:
        """The type's relations that some check or derivation reads."""

        filter_reads = (
            self.relations_read(name).get(entity_type, frozenset())
            for name in self.role_filters
        )

        return frozenset(
            self._status_relations(entity_type).union(
                self._gated_relations(entity_type),
                self.derivation_reads.get(entity_type, frozenset()),
                *filter_reads,
            )
        )

    def _gated_relations(self, entity_type: str) -> set[str]:
        """The relations of the type that an action or endpoint gate reads."""

        gated: set[str] = set()

        for action in self.action_types.values():
            if isinstance(action, MutateAction):
                if action.referent_type == entity_type:
                    gated.update(action.gate)
                continue

            targets = self.entity_types[action.referent_type].links
            for link, gate in action.links.items():
                if entity_type in targets[link]:
                    gated.update(gate)

        return gated

    def _status_relations(self, entity_type: str) -> set[str]:
        """The type's status relation, none for a type without one."""

        status = self.entity_types[entity_type].status

        return set() if status is None else {status}
