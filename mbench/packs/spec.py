from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any

from mbench.core.values.protocol import ValueClass
from mbench.core.values.samplers import Sampler

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
class Copy:
    """A first value copied from the entity one of the INIT's links reaches."""

    via: str
    relation: str


@dataclass(frozen=True)
class ByType:
    """A first value chosen by the type of the entity a link reaches."""

    via: str
    values: Mapping[str, ValueClass]

    def __post_init__(self) -> None:
        """Hold the values read-only."""

        object.__setattr__(self, "values", MappingProxyType(dict(self.values)))


@dataclass(frozen=True)
class CopyLink:
    """A structural link copied from the entity a link of the INIT reaches."""

    via: str
    link: str


@dataclass(frozen=True)
class InitAction:
    """An ActionType that creates an entity of its referent type."""

    name: str
    referent_type: str
    # The links the command names, each with the gate its endpoint must pass.
    links: Mapping[str, Gate] = field(
        default_factory=lambda: MappingProxyType({})
    )
    # The values the INIT itself sets, never chosen per command. Its entry
    # status is one: for variety a pack adds another INIT.
    fixes: Mapping[str, ValueClass] = field(
        default_factory=lambda: MappingProxyType({})
    )
    # The values computed from the linked entities when the INIT is decided,
    # so a command never carries them.
    derives: Mapping[str, Copy | ByType] = field(
        default_factory=lambda: MappingProxyType({})
    )
    # The links computed the same way, which a command does not name.
    copied_links: Mapping[str, CopyLink] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def __post_init__(self) -> None:
        """Hold the links, their gates and the INIT's recipe read-only."""

        object.__setattr__(self, "links", _frozen_gates(self.links))
        for table in ("fixes", "derives", "copied_links"):
            object.__setattr__(
                self, table, MappingProxyType(dict(getattr(self, table)))
            )


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


def default_source(
    initiator: str,
    named: str | None,
    speakers: Iterable[Speaker],
    sources: Iterable[Source],
) -> str:
    """The source named, else the initiator's speaker, else a document."""

    if named is not None:
        return named

    for speaker in speakers:
        if speaker.represents == initiator:
            return speaker.id

    # Any document will do, the first declared keeps a replay stable.
    for source in sources:
        if source.kind is SourceKind.DOCUMENT:
            return source.id

    # An off-stage actor in a pack with no document is the pack's bug, not a
    # refusal a clause would count.
    raise LookupError(f"no source can state an event of {initiator}")


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
    # None admits an entity of any type.
    entity_type: str | None
    # The values the entity must hold, per relation.
    values: Gate = field(default_factory=lambda: MappingProxyType({}))
    # Whether the entity's current status must be non-terminal.
    live: bool = False
    # The entity must have no live entity pointing at it in any of these ways.
    no_live_linkers: tuple[Linker, ...] = ()
    # A role the entity must link to the binding of, by any of its links.
    of: str | None = None

    def __post_init__(self) -> None:
        """Hold the required values read-only."""

        object.__setattr__(self, "values", _frozen_gate(self.values))


type _Reads = Mapping[str, frozenset[str]]


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
    pools: Mapping[str, Pool[Any]] = field(
        default_factory=lambda: MappingProxyType({})
    )
    # First values per (INIT, relation). An INIT's run in this order, so one
    # may read the relations declared before it.
    init_samplers: Mapping[tuple[str, str], Sampler[Any]] = field(
        default_factory=lambda: MappingProxyType({})
    )
    # Next values per (entity type, relation).
    step_samplers: Mapping[tuple[str, str], Sampler[Any]] = field(
        default_factory=lambda: MappingProxyType({})
    )

    # The tables below are derived from the declarations on construction, so
    # a pack made by `replace` holds its own, never those of its original.

    # Per entity type, the relations some check or derivation reads.
    relations_legality_reads: _Reads = field(
        init=False, repr=False, compare=False
    )
    # Per role filter, then per entity type, the relations the filter reads.
    filter_reads: Mapping[str, _Reads] = field(
        init=False, repr=False, compare=False
    )
    # Per entity type, the relations an INIT's derivations read of it.
    derivation_reads: _Reads = field(init=False, repr=False, compare=False)
    # Per ActionType with framings, the initiators the owner does not state.
    contestable_initiators: Mapping[str, frozenset[str]] = field(
        init=False, repr=False, compare=False
    )
    # Per actor, the source of its events when a command names none.
    default_sources: Mapping[str, str] = field(
        init=False, repr=False, compare=False
    )
    # Per (entity type, relation), the MUTATEs writing it, in declaration
    # order. Not per transition: a gate on the relation written decides
    # which MUTATE takes a change, and a status move may have no gate.
    _writers: Mapping[tuple[str, str], tuple[MutateAction, ...]] = field(
        init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        """Hold every table read-only, refuse bad names, derive the queries."""

        for table in (
            "entity_types",
            "action_types",
            "actors",
            "speakers",
            "sources",
            "role_filters",
            "framings",
            "pools",
            "init_samplers",
            "step_samplers",
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

        # Every later status check reads the status an INIT starts it at.
        unfixed = [
            action.name
            for action in self.action_types.values()
            if isinstance(action, InitAction)
            and not _fixes_entry_status(self.entity_types, action)
        ]
        if unfixed:
            raise ValueError(f"INITs fix no entry status: {sorted(unfixed)}")

        self._derive_tables()

    def _derive_tables(self) -> None:
        """Compute the tables legality queries, once per pack."""

        filter_reads = {
            name: _filter_reads(role_filter, self.entity_types)
            for name, role_filter in self.role_filters.items()
        }
        derivation_reads = _derivation_reads(
            self.entity_types, self.action_types
        )
        legality_reads = _legality_reads(
            self.entity_types,
            self.action_types,
            derivation_reads,
            filter_reads.values(),
        )
        contestable = _contestable_initiators(
            self.framings, self.speakers, self.owner
        )
        defaults = _default_sources(self.actors, self.speakers, self.sources)

        set_table = object.__setattr__
        set_table(self, "filter_reads", MappingProxyType(filter_reads))
        set_table(self, "derivation_reads", MappingProxyType(derivation_reads))
        set_table(
            self, "relations_legality_reads", MappingProxyType(legality_reads)
        )
        set_table(self, "contestable_initiators", MappingProxyType(contestable))
        set_table(self, "default_sources", MappingProxyType(defaults))
        set_table(
            self, "_writers", MappingProxyType(_writers(self.action_types))
        )

    def action_for(
        self, entity_type: str, relation: str, transition: Transition
    ) -> MutateAction | None:
        """The ActionType that makes this write on this type, if one does."""

        candidates = self._writers.get((entity_type, relation), ())

        return next(
            (action for action in candidates if action.takes(transition)),
            None,
        )

    def passes_owner_rule(self, action: str) -> bool:
        """Whether someone other than the owner's speaker states the action."""

        return bool(self.contestable_initiators.get(action, frozenset()))

    def shared_initiators(self, first: str, second: str) -> frozenset[str]:
        """The initiators both actions have a contestable framing for."""

        initiators = self.contestable_initiators

        return initiators.get(first, frozenset()) & initiators.get(
            second, frozenset()
        )


def _fixes_entry_status(
    entity_types: Mapping[str, EntityType], action: InitAction
) -> bool:
    """Whether the INIT fixes its type's status, if the type has one."""

    entity_type = entity_types.get(action.referent_type)

    return (
        entity_type is None
        or entity_type.status is None
        or entity_type.status in action.fixes
    )


def _status_relations(
    entity_types: Mapping[str, EntityType], entity_type: str
) -> set[str]:
    """The type's status relation, none for a type without one."""

    status = entity_types[entity_type].status

    return set() if status is None else {status}


def _gated_relations(
    entity_types: Mapping[str, EntityType],
    action_types: Mapping[str, ActionType],
    entity_type: str,
) -> set[str]:
    """The relations of the type that an action or endpoint gate reads."""

    gated: set[str] = set()

    for action in action_types.values():
        if isinstance(action, MutateAction):
            if action.referent_type == entity_type:
                gated.update(action.gate)
            continue

        targets = entity_types[action.referent_type].links
        for link, gate in action.links.items():
            if entity_type in targets[link]:
                gated.update(gate)

    return gated


def _filter_reads(
    role_filter: RoleFilter, entity_types: Mapping[str, EntityType]
) -> _Reads:
    """The relations, per entity type, that the role filter reads."""

    # A filter of any type reads its relations wherever a type has them.
    types = (
        entity_types
        if role_filter.entity_type is None
        else (role_filter.entity_type,)
    )
    reads: dict[str, set[str]] = {}

    for entity_type in types:
        read = set(role_filter.values) & set(
            entity_types[entity_type].relations
        )
        if role_filter.live:
            read |= _status_relations(entity_types, entity_type)
        reads[entity_type] = read

    # A link is never contested, so `of` reads no relation.
    for linker in role_filter.no_live_linkers:
        reads.setdefault(linker.entity_type, set()).update(
            {linker.link} | _status_relations(entity_types, linker.entity_type)
        )

    # Read-only itself, as the pack's table holds it under the filter's name.
    return MappingProxyType(
        {
            entity_type: frozenset(relations)
            for entity_type, relations in reads.items()
        }
    )


def _derivation_reads(
    entity_types: Mapping[str, EntityType],
    action_types: Mapping[str, ActionType],
) -> _Reads:
    """The relations, per entity type, that an INIT's `Copy` reads of it."""

    reads: dict[str, set[str]] = {name: set() for name in entity_types}

    # A `ByType` reads only the type, a `CopyLink` only a link, so neither
    # reads a relation. A `via` naming no link is the predicate's to report.
    for action in action_types.values():
        if not isinstance(action, InitAction):
            continue
        links = entity_types[action.referent_type].links
        for derivation in action.derives.values():
            if not isinstance(derivation, Copy):
                continue
            for target in links.get(derivation.via, ()):
                reads.setdefault(target, set()).add(derivation.relation)

    return {
        entity_type: frozenset(relations)
        for entity_type, relations in reads.items()
    }


def _legality_reads(
    entity_types: Mapping[str, EntityType],
    action_types: Mapping[str, ActionType],
    derivation_reads: _Reads,
    filter_reads: Iterable[_Reads],
) -> _Reads:
    """The relations, per entity type, that some check or derivation reads."""

    # Mirrors every read site of legality, so a new kind of read there must
    # be added here: referent and writer gates (`_passes` in the predicate),
    # INIT endpoint gates, role filters (`role_filters.judge`), liveness, and
    # derivations (the predicate's `_derive`).
    filter_reads = tuple(filter_reads)

    return {
        entity_type: frozenset(
            _status_relations(entity_types, entity_type).union(
                _gated_relations(entity_types, action_types, entity_type),
                derivation_reads.get(entity_type, frozenset()),
                *(
                    reads.get(entity_type, frozenset())
                    for reads in filter_reads
                ),
            )
        )
        for entity_type in entity_types
    }


def _contestable_initiators(
    framings: Mapping[str, tuple[Framing, ...]],
    speakers: Mapping[str, Speaker],
    owner: str,
) -> Mapping[str, frozenset[str]]:
    """Per action, the initiators of its framings the owner does not state."""

    # The owner can't be unsure of a change it stated itself.
    owners_speakers = {
        speaker.id
        for speaker in speakers.values()
        if speaker.represents == owner
    }

    return {
        action: frozenset(
            framing.initiator
            for framing in group
            if framing.source not in owners_speakers
        )
        for action, group in framings.items()
    }


def _default_sources(
    actors: Mapping[str, Actor],
    speakers: Mapping[str, Speaker],
    sources: Mapping[str, Source],
) -> Mapping[str, str]:
    """Per actor, its default source, refusing an actor that has none."""

    defaults: dict[str, str] = {}
    sourceless: list[str] = []

    for actor in actors:
        try:
            defaults[actor] = default_source(
                actor, None, speakers.values(), sources.values()
            )
        except LookupError:
            sourceless.append(actor)

    # Caught here, the pack's bug never waits for a command to run.
    if sourceless:
        raise ValueError(
            f"actors with no speaker and no document: {sorted(sourceless)}"
        )

    return defaults


def _writers(
    action_types: Mapping[str, ActionType],
) -> Mapping[tuple[str, str], tuple[MutateAction, ...]]:
    """Per (entity type, relation), the MUTATEs writing it, in order."""

    writers: dict[tuple[str, str], list[MutateAction]] = {}

    for action in action_types.values():
        if isinstance(action, MutateAction):
            key = (action.referent_type, action.relation)
            writers.setdefault(key, []).append(action)

    return {key: tuple(actions) for key, actions in writers.items()}
