from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import Enum

from mbench.core.folds.registry import (
    Entry,
    Registry,
    Stamped,
    is_contested,
    is_live,
)
from mbench.core.legality.role_filters import Verdict, judge, judge_gate
from mbench.core.records.commands import (
    AgreeingDoubleDisclosureCommand,
    Command,
    ConflictingDoubleDisclosureCommand,
    EventCommand,
    InitCommand,
    MutateCommand,
    ReadCommand,
)
from mbench.core.records.ids import IdAllocator, NodeId
from mbench.core.records.log import (
    CONTEST,
    READ,
    AcceptedCommand,
    Disclosure,
    Event,
    InitEvent,
    Link,
    MutateEvent,
    Record,
)
from mbench.core.values.contested import Contested, WorldValue
from mbench.core.values.protocol import ValueClass, Zone, ZonedValueClass
from mbench.packs.spec import (
    ByType,
    Copy,
    EntityType,
    Gate,
    InitAction,
    LoadedPack,
    MutateAction,
    SourceKind,
    default_source,
)


class Reason(Enum):
    """Why a command was refused, a stable code the refusals are counted by."""

    REFERENT_MISSING = "referent_missing"
    REFERENT_WRONG_TYPE = "referent_wrong_type"
    GATE_FAILED = "gate_failed"
    NOT_LIVE = "not_live"
    ENDPOINT_MISSING = "endpoint_missing"
    ENDPOINT_WRONG_TYPE = "endpoint_wrong_type"
    ENDPOINT_GATE_FAILED = "endpoint_gate_failed"
    ENDPOINT_FILTER_FAILED = "endpoint_filter_failed"
    PAIR_ALREADY_WRITTEN = "pair_already_written"
    INVALID_VALUE = "invalid_value"
    UNTRUE_DISCLOSURE = "untrue_disclosure"
    UNEQUAL_AUTHORITY = "unequal_authority"
    SPEAKER_TWICE = "speaker_twice"
    CONTESTED_VALUES_EQUAL = "contested_values_equal"
    CONTESTED_VALUE_IS_CURRENT = "contested_value_is_current"
    NO_WRITER = "no_writer"
    WRITER_GATE_FAILED = "writer_gate_failed"
    NO_CONTESTABLE_FRAMING = "no_contestable_framing"
    INITIATOR_NOT_SHARED = "initiator_not_shared"
    PAIR_SEALED = "pair_sealed"
    ENTITY_SEALED = "entity_sealed"
    ANCHOR_SAME_ZONE = "anchor_same_zone"
    UNCHANGED_VALUE = "unchanged_value"


@dataclass(frozen=True)
class Refusal:
    """Why a command was refused: the reason its first failing clause gives."""

    reason: Reason


def decide(
    command: Command,
    registry: Registry,
    pack: LoadedPack,
    allocator: IdAllocator,
) -> AcceptedCommand | Refusal:
    """The command with the records it produces, or why it is refused."""

    resolved = _checked(command, registry, pack)
    if isinstance(resolved, Refusal):
        return resolved

    return AcceptedCommand(command, resolved.records(allocator))


def check(
    command: Command, registry: Registry, pack: LoadedPack
) -> Refusal | None:
    """Why the command is illegal at this registry, if it is."""

    resolved = _checked(command, registry, pack)

    return resolved if isinstance(resolved, Refusal) else None


def refuse_untrue_disclosure(
    disclosure: Disclosure, registry: Registry
) -> Refusal | None:
    """Refuse a disclosure of a value or link the world does not hold."""

    entry = registry.entry(disclosure.entity)
    if entry is None:
        return Refusal(Reason.UNTRUE_DISCLOSURE)

    if isinstance(disclosure.value, Link):
        holds = entry.links.get(disclosure.relation) == disclosure.value.target
    else:
        current = entry.values.get(disclosure.relation)
        holds = current is not None and _admits(current.value, disclosure.value)

    return None if holds else Refusal(Reason.UNTRUE_DISCLOSURE)


@dataclass(frozen=True)
class _Read:
    """A READ the check has passed, with the entity it states."""

    command: ReadCommand
    entry: Entry

    def records(self, allocator: IdAllocator) -> tuple[Record, ...]:
        """The READ's disclosures of the entity's current values."""

        # Each value is copied from the registry, so these disclosures always
        # pass `refuse_untrue_disclosure`, only a disclosure written by other
        # means, as in a stored log, can fail it.
        return tuple(
            Disclosure(
                session=self.command.session,
                source=self.command.source,
                action_type=READ,
                initiator=self.command.initiator,
                entity=self.command.entity,
                relation=relation,
                value=_readable(current.value),
                node_id=allocator.allocate(),
            )
            for relation, current in self.entry.values.items()
        )


@dataclass(frozen=True)
class _Mutate:
    """A plain write of one value on a referent: a MUTATE or agreeing pair."""

    command: MutateCommand | AgreeingDoubleDisclosureCommand
    writes: Mapping[str, ValueClass]
    sources: tuple[str, ...]
    entry: Entry
    # The current stamped value of each pair it writes, if any.
    current: Mapping[str, Stamped]

    def records(self, allocator: IdAllocator) -> tuple[Record, ...]:
        """The MUTATE event, then one disclosure of its value per source."""

        event = MutateEvent(
            session=self.command.session,
            initiator=self.command.initiator,
            action_type=self.command.action_type,
            referent=self.command.referent,
            writes=self.writes,
        )

        return (
            event,
            *(
                disclosure
                for source in self.sources
                for disclosure in _disclosures(
                    event, event.referent, self.writes, source, allocator
                )
            ),
        )


@dataclass(frozen=True)
class _Contest:
    """A contested write, with the ActionType that writes each of its values."""

    command: ConflictingDoubleDisclosureCommand
    writes: Mapping[str, WorldValue]
    writers: tuple[MutateAction, MutateAction]

    def records(self, allocator: IdAllocator) -> tuple[Record, ...]:
        """The CONTEST event, then each source's disclosure of its own value."""

        command = self.command
        event = MutateEvent(
            session=command.session,
            initiator=command.initiator,
            action_type=CONTEST,
            referent=command.referent,
            writes=self.writes,
        )

        return (
            event,
            *(
                Disclosure(
                    session=event.session,
                    source=source,
                    action_type=writer.name,
                    initiator=event.initiator,
                    entity=event.referent,
                    relation=command.relation,
                    value=value,
                    node_id=allocator.allocate(),
                )
                for source, value, writer in zip(
                    command.sources,
                    (command.a, command.b),
                    self.writers,
                    strict=True,
                )
            ),
        )


@dataclass(frozen=True)
class _Init:
    """An INIT with its endpoints and what derives from them."""

    command: InitCommand
    action: InitAction
    source: str
    endpoints: Mapping[str, Entry]
    # The links whose role filter cannot judge its endpoint for a conflict.
    undecided: frozenset[str]
    derived: Mapping[str, ValueClass]
    copied: Mapping[str, NodeId]
    # The command's values and the derived ones: all the event writes.
    writes: Mapping[str, ValueClass]

    def records(self, allocator: IdAllocator) -> tuple[Record, ...]:
        """The INIT event, then a default disclosure per value and link."""

        event = InitEvent(
            session=self.command.session,
            initiator=self.command.initiator,
            action_type=self.command.action_type,
            new_id=allocator.allocate(),
            writes=self.writes,
            links={**self.command.links, **self.copied},
        )

        links = {link: Link(target) for link, target in event.links.items()}

        return (
            event,
            *_disclosures(
                event,
                event.new_id,
                {**event.writes, **links},
                self.source,
                allocator,
            ),
        )


type _Resolved = _Read | _Mutate | _Contest | _Init


def _checked(
    command: Command, registry: Registry, pack: LoadedPack
) -> Refusal | _Resolved:
    """What the command will do, or why it is illegal at this registry."""

    _check_names(command, pack)

    if isinstance(command, ReadCommand):
        return _checked_read(command, registry)
    if isinstance(command, ConflictingDoubleDisclosureCommand):
        return _checked_contest(command, registry, pack)
    if isinstance(command, InitCommand):
        return _checked_init(command, registry, pack)

    return _checked_mutate(command, registry, pack)


def _checked_read(command: ReadCommand, registry: Registry) -> Refusal | _Read:
    """The READ with its entity, unless that is missing or sealed."""

    entry = registry.entry(command.entity)
    if entry is None:
        return Refusal(Reason.REFERENT_MISSING)

    # A READ states every value of its entity, so one contested pair is enough.
    return _refuse_sealed(entry.values.values()) or _Read(command, entry)


def _checked_mutate(
    command: MutateCommand | AgreeingDoubleDisclosureCommand,
    registry: Registry,
    pack: LoadedPack,
) -> Refusal | _Mutate:
    """The plain write resolved, or the first clause that refuses it."""

    action = _mutate_action(command, pack)
    writes = {action.relation: _written_value(command, action)}

    sources: tuple[str, ...]
    if isinstance(command, AgreeingDoubleDisclosureCommand):
        sources = command.sources
    else:
        sources = (_default_source(command.initiator, command.source, pack),)

    mutate = _resolve_referent(command, action, writes, sources, registry, pack)
    if isinstance(mutate, Refusal):
        return mutate

    relations = pack.entity_types[action.referent_type].relations
    refusal = (
        _refuse_second_write(command.session, mutate.current)
        or _refuse_invalid_values(relations, writes.items())
        or _refuse_sealed(mutate.current.values())
        or _refuse_sealed_entity(mutate.entry, pack)
        or _refuse_unchanged_value(writes, mutate.current)
    )

    return refusal or mutate


def _checked_contest(
    command: ConflictingDoubleDisclosureCommand,
    registry: Registry,
    pack: LoadedPack,
) -> Refusal | _Contest:
    """The contested write resolved, or the first clause that refuses it."""

    writes = {command.relation: Contested(command.a, command.b)}

    entry = _contested_referent(command, registry, pack)
    if isinstance(entry, Refusal):
        return entry

    current = _current(entry, writes)
    relations = pack.entity_types[entry.type].relations
    stated = ((command.relation, command.a), (command.relation, command.b))

    # Sealing runs just before the writers: it refuses exactly a pair already
    # contested, which no writer can write from, so the writers never see one
    # and either order gives every command the same refusal.
    refusal = (
        _refuse_second_write(command.session, current)
        or _refuse_invalid_values(relations, stated)
        or _refuse_contest_sources(command, pack)
        or _refuse_contest_values(command, entry)
        or _refuse_sealed(current.values())
    )
    if refusal is not None:
        return refusal

    writers = _contest_writers(command, entry, pack)
    if isinstance(writers, Refusal):
        return writers

    refusal = _refuse_sealed_entity(entry, pack) or _refuse_unchanged_value(
        writes, current
    )

    return refusal or _Contest(command, writes, writers)


def _checked_init(
    command: InitCommand, registry: Registry, pack: LoadedPack
) -> Refusal | _Init:
    """The INIT resolved, or the first clause that refuses it."""

    action = _init_action(command, pack)
    _check_links(command, action, pack)
    _check_fixed_values(command, action)
    _check_no_derived_writes(command, action)
    source = _default_source(command.initiator, command.source, pack)

    init = _resolve_endpoints(command, action, source, registry, pack)
    if isinstance(init, Refusal):
        return init

    entity_type = pack.entity_types[action.referent_type]
    refusal = (
        _refuse_invalid_values(entity_type.relations, command.writes.items())
        or _refuse_init_on_conflict(init, registry, pack)
        or _refuse_anchor(entity_type, init.writes, registry)
    )
    if refusal is None:
        _check_derivations(init, pack)

    return refusal or init


def _resolve_referent(
    command: MutateCommand | AgreeingDoubleDisclosureCommand,
    action: MutateAction,
    writes: Mapping[str, ValueClass],
    sources: tuple[str, ...],
    registry: Registry,
    pack: LoadedPack,
) -> Refusal | _Mutate:
    """Refuse a write on a missing, mistyped, gated-out or dead referent."""

    entry = registry.entry(command.referent)
    if entry is None:
        return Refusal(Reason.REFERENT_MISSING)
    if entry.type != action.referent_type:
        return Refusal(Reason.REFERENT_WRONG_TYPE)
    if not _passes(entry, action.gate):
        return Refusal(Reason.GATE_FAILED)

    # A gate that reads the status has named the statuses it admits, a
    # terminal one included, so it, not liveness, decides.
    status = pack.entity_types[entry.type].status
    if status not in action.gate and not is_live(entry, pack):
        return Refusal(Reason.NOT_LIVE)

    return _Mutate(command, writes, sources, entry, _current(entry, writes))


def _contested_referent(
    command: ConflictingDoubleDisclosureCommand,
    registry: Registry,
    pack: LoadedPack,
) -> Refusal | Entry:
    """The contested pair's entity, unless it is missing or dead."""

    entry = registry.entry(command.referent)
    if entry is None:
        return Refusal(Reason.REFERENT_MISSING)

    # It names no ActionType, so it has no referent type or gate of its own.
    return entry if is_live(entry, pack) else Refusal(Reason.NOT_LIVE)


def _resolve_endpoints(
    command: InitCommand,
    action: InitAction,
    source: str,
    registry: Registry,
    pack: LoadedPack,
) -> Refusal | _Init:
    """Refuse an INIT whose endpoint is missing, mistyped, gated or filtered."""

    targets = pack.entity_types[action.referent_type].links
    endpoints = {}
    undecided = set()

    # An endpoint need not be live: a replacement points at the closed card
    # it replaces. A gate or filter that wants a live one says so.
    for link, endpoint in command.links.items():
        entry = registry.entry(endpoint)

        if entry is None:
            return Refusal(Reason.ENDPOINT_MISSING)
        if entry.type not in targets[link]:
            return Refusal(Reason.ENDPOINT_WRONG_TYPE)
        if not _passes(entry, action.links[link]):
            return Refusal(Reason.ENDPOINT_GATE_FAILED)

        verdict = _filter_verdict(command, link, entry, registry, pack)
        if verdict is Verdict.FAIL:
            return Refusal(Reason.ENDPOINT_FILTER_FAILED)
        if verdict is Verdict.UNDECIDED:
            undecided.add(link)

        endpoints[link] = entry

    derived = _derived_values(action, endpoints)

    return _Init(
        command=command,
        action=action,
        source=source,
        endpoints=endpoints,
        undecided=frozenset(undecided),
        derived=derived,
        copied=_copied_links(action, endpoints),
        writes={**command.writes, **derived},
    )


def _refuse_second_write(
    session: int, current: Mapping[str, Stamped]
) -> Refusal | None:
    """Refuse a write to a pair already written in the command's session."""

    for stamped in current.values():
        if stamped.session == session:
            return Refusal(Reason.PAIR_ALREADY_WRITTEN)

    return None


def _refuse_invalid_values(
    relations: Mapping[str, type[ValueClass]],
    stated: Iterable[tuple[str, ValueClass]],
) -> Refusal | None:
    """Refuse a value its relation's class does not hold, or holds invalid."""

    for relation, value in stated:
        if not _fits(relations, relation, value):
            return Refusal(Reason.INVALID_VALUE)

    return None


def _fits(
    relations: Mapping[str, type[ValueClass]], relation: str, value: ValueClass
) -> bool:
    """Whether the relation is declared and its class holds the value."""

    cls = relations.get(relation)

    return cls is not None and isinstance(value, cls) and value.is_valid()


def _refuse_contest_sources(
    command: ConflictingDoubleDisclosureCommand, pack: LoadedPack
) -> Refusal | None:
    """Refuse sources of unequal authority, or one speaker named twice."""

    first, second = (pack.sources[source] for source in command.sources)

    if first.authority != second.authority:
        return Refusal(Reason.UNEQUAL_AUTHORITY)

    # Two letters are two messages, one person giving two figures is a
    # self-correction.
    if first.id == second.id and first.kind is SourceKind.SPEAKER:
        return Refusal(Reason.SPEAKER_TWICE)

    return None


def _refuse_contest_values(
    command: ConflictingDoubleDisclosureCommand, entry: Entry
) -> Refusal | None:
    """Refuse two equal values, or one the pair already holds."""

    if command.a == command.b:
        return Refusal(Reason.CONTESTED_VALUES_EQUAL)

    # Only the current value: the registry keeps no earlier versions, so
    # whoever draws the two values must avoid those.
    current = entry.values.get(command.relation)
    if current is not None and current.value in (command.a, command.b):
        return Refusal(Reason.CONTESTED_VALUE_IS_CURRENT)

    return None


def _contest_writers(
    command: ConflictingDoubleDisclosureCommand,
    entry: Entry,
    pack: LoadedPack,
) -> Refusal | tuple[MutateAction, MutateAction]:
    """The unstated, co-initiated ActionTypes that write each value, if any."""

    writers = []
    for value in (command.a, command.b):
        writer = _find_writer(entry, command.relation, value, pack)
        if writer is None:
            return Refusal(Reason.NO_WRITER)
        if not _passes(entry, writer.gate):
            return Refusal(Reason.WRITER_GATE_FAILED)
        if not pack.passes_owner_rule(writer.name):
            return Refusal(Reason.NO_CONTESTABLE_FRAMING)
        writers.append(writer)

    # The command names the initiator, since two framings may share several.
    first, second = writers
    if command.initiator not in pack.shared_initiators(first.name, second.name):
        return Refusal(Reason.INITIATOR_NOT_SHARED)

    return first, second


def _find_writer(
    entry: Entry, relation: str, value: ValueClass, pack: LoadedPack
) -> MutateAction | None:
    """The ActionType that would write the value over the pair's current."""

    stamped = entry.values.get(relation)
    if stamped is None or isinstance(stamped.value, Contested):
        return None

    return pack.action_for(entry.type, relation, (stamped.value, value))


def _refuse_sealed(values: Iterable[Stamped]) -> Refusal | None:
    """Refuse a command touching these values if any is contested."""

    if any(isinstance(current.value, Contested) for current in values):
        return Refusal(Reason.PAIR_SEALED)

    return None


def _refuse_sealed_entity(entry: Entry, pack: LoadedPack) -> Refusal | None:
    """Refuse a write to an entity with no truth to read in its gates."""

    return (
        Refusal(Reason.ENTITY_SEALED)
        if _entity_is_sealed(entry, pack)
        else None
    )


def _refuse_init_on_conflict(
    init: _Init, registry: Registry, pack: LoadedPack
) -> Refusal | None:
    """Refuse an INIT whose link's target is sealed, or its filter undecided."""

    # An undecided filter reads a conflict such as a linking entity's
    # contested status, which no relation of the endpoint holds, so sealing
    # it would not catch.
    sealed = any(
        _entity_is_sealed(entry, pack) or link in init.undecided
        for link, entry in init.endpoints.items()
    ) or any(
        _entity_is_sealed(_linked_entry(target, registry), pack)
        for target in init.copied.values()
    )

    return Refusal(Reason.ENTITY_SEALED) if sealed else None


def _linked_entry(target: NodeId, registry: Registry) -> Entry:
    """The entity a stored link points at."""

    entry = registry.entry(target)
    # A link is stored only to an entity the registry holds, and the registry
    # drops none.
    assert entry is not None

    return entry


def _entity_is_sealed(entry: Entry, pack: LoadedPack) -> bool:
    """Whether a relation legality reads holds a contested value."""

    contested = {r for r in entry.values if is_contested(entry, r)}
    if not contested:
        return False

    return not contested.isdisjoint(pack.relations_legality_reads(entry.type))


def _refuse_anchor(
    entity_type: EntityType,
    writes: Mapping[str, ValueClass],
    registry: Registry,
) -> Refusal | None:
    """Refuse values whose anchor is in the same zone as one of the type's."""

    if not entity_type.anchor:
        return None

    # Closed entities count too: a question may name one, so its anchor
    # must still pick it out alone.
    for entry in registry.entries():
        if entry.type == entity_type.name and all(
            _same_part(writes, entry, part) for part in entity_type.anchor
        ):
            return Refusal(Reason.ANCHOR_SAME_ZONE)

    return None


def _same_part(
    writes: Mapping[str, ValueClass], entry: Entry, part: str
) -> bool:
    """Whether the INIT's anchor part is in the same zone as the entry's."""

    # Nothing yet makes an INIT write every relation, and a part one side
    # lacks cannot make the two anchors alike.
    if part not in writes or part not in entry.values:
        return False

    new, existing = writes[part], entry.values[part].value

    # The loaded type has refused a nameable anchor without zones, so a part
    # without them belongs to a type never named, compared by equality.
    if isinstance(new, ZonedValueClass) and isinstance(existing, type(new)):
        return new.zone(existing) is Zone.SAME

    return new == existing


def _refuse_unchanged_value(
    writes: Mapping[str, WorldValue], current: Mapping[str, Stamped]
) -> Refusal | None:
    """Refuse a write of the value its pair already holds."""

    for relation, stamped in current.items():
        if writes[relation] == stamped.value:
            return Refusal(Reason.UNCHANGED_VALUE)

    return None


def _admits(current: WorldValue, stated: ValueClass) -> bool:
    """Whether a pair holding the current value may be said to hold another."""

    if isinstance(current, Contested):
        return stated in current.members

    return stated == current


def _current(
    entry: Entry, writes: Mapping[str, WorldValue]
) -> Mapping[str, Stamped]:
    """The current stamped value of each pair the writes touch, if any."""

    return {
        relation: entry.values[relation]
        for relation in writes
        if relation in entry.values
    }


def _derived_values(
    action: InitAction, endpoints: Mapping[str, Entry]
) -> dict[str, ValueClass]:
    """The values the INIT's derivations give, skipping any with no answer."""

    # A clause may yet refuse the INIT, and a refused INIT needs no derived
    # values, so one with nothing to read is skipped here rather than raised.
    # `_check_derivations` has the final say on an INIT the clauses pass.
    derived = {}

    for relation, derivation in action.derives.items():
        source = endpoints.get(derivation.via)
        value = None if source is None else _derive(derivation, source)
        if value is not None and not isinstance(value, Contested):
            derived[relation] = value

    return derived


def _derive(derivation: Copy | ByType, source: Entry) -> WorldValue | None:
    """The value the derivation reads off its source entity, if any."""

    if isinstance(derivation, ByType):
        return derivation.values.get(source.type)

    stamped = source.values.get(derivation.relation)

    return None if stamped is None else stamped.value


def _copied_links(
    action: InitAction, endpoints: Mapping[str, Entry]
) -> dict[str, NodeId]:
    """The links the INIT copies, skipping any with nothing to copy."""

    copied = {}

    for link, derivation in action.copied_links.items():
        source = endpoints.get(derivation.via)
        target = None if source is None else source.links.get(derivation.link)
        if target is not None:
            copied[link] = target

    return copied


def _check_names(command: Command, pack: LoadedPack) -> None:
    """Raise unless the command names a declared initiator and sources."""

    # No clause covers the names a command gives, so a wrong one is the
    # caller's bug, raised rather than refused. A conflict may come from one
    # document twice, but an agreeing pair needs two.
    if command.initiator not in pack.actors:
        raise ValueError(f"the pack declares no initiator {command.initiator}")

    sources = _named_sources(command)
    if isinstance(command, AgreeingDoubleDisclosureCommand):
        first, second = sources
        if first == second:
            raise ValueError(
                f"{first} is named twice, not two different sources"
            )

    unknown = set(sources) - pack.sources.keys()
    if unknown:
        raise ValueError(f"the pack declares no source {sorted(unknown)}")


def _named_sources(command: Command) -> tuple[str, ...]:
    """The sources the command names, none if it leaves them to the default."""

    if isinstance(
        command,
        AgreeingDoubleDisclosureCommand | ConflictingDoubleDisclosureCommand,
    ):
        return command.sources

    # None leaves the source to the default, which names a declared one.
    return () if command.source is None else (command.source,)


def _default_source(initiator: str, named: str | None, pack: LoadedPack) -> str:
    """The source of an event's disclosures, the named one if any."""

    return default_source(
        initiator, named, pack.speakers.values(), pack.sources.values()
    )


def _init_action(command: InitCommand, pack: LoadedPack) -> InitAction:
    """The INIT ActionType the command names."""

    action = pack.action_types[command.action_type]
    if not isinstance(action, InitAction):
        raise _wrong_shape(command, action.name)

    return action


def _mutate_action(
    command: MutateCommand | AgreeingDoubleDisclosureCommand, pack: LoadedPack
) -> MutateAction:
    """The MUTATE ActionType the command names."""

    action = pack.action_types[command.action_type]
    if not isinstance(action, MutateAction):
        raise _wrong_shape(command, action.name)

    return action


def _wrong_shape(command: EventCommand, action: str) -> TypeError:
    """The error for a command naming an ActionType of the other shape."""

    # A caller's bug, raised like an unknown name, not a refusal a clause
    # would count.
    return TypeError(f"{type(command).__name__} cannot take {action}")


def _check_links(
    command: InitCommand, action: InitAction, pack: LoadedPack
) -> None:
    """Raise unless an INIT fills its links and names filters it can use."""

    # Like a command of the wrong shape: the caller fills every link the
    # INIT does not copy, and a link it lacks or may not name is its bug.
    if command.links.keys() != action.links.keys():
        raise ValueError(
            f"{action.name} takes links {sorted(action.links)},"
            f" not {sorted(command.links)}"
        )
    if not command.filters.keys() <= action.links.keys():
        raise ValueError(
            f"{action.name} writes no link to filter among"
            f" {sorted(command.filters.keys() - action.links.keys())}"
        )

    unknown = set(command.filters.values()) - pack.role_filters.keys()
    if unknown:
        raise ValueError(
            f"{action.name} names role filters the pack lacks:"
            f" {sorted(unknown)}"
        )

    # A command stores no bindings, so replay could not judge one of these.
    relating = sorted(
        name
        for name in set(command.filters.values())
        if pack.role_filters[name].of is not None
    )
    if relating:
        raise ValueError(
            f"{action.name} names role filters relating two roles: {relating}"
        )


def _check_fixed_values(command: InitCommand, action: InitAction) -> None:
    """Raise unless an INIT writes exactly the values its ActionType fixes."""

    # The pack fixes these, so a command that gets one wrong is its caller's
    # bug. Left unwritten, a status would break every later read of it.
    wrong = [
        relation
        for relation, value in action.fixes.items()
        if command.writes.get(relation) != value
    ]
    if wrong:
        raise ValueError(
            f"{action.name} fixes {sorted(wrong)}, the command differs"
        )


def _check_no_derived_writes(command: InitCommand, action: InitAction) -> None:
    """Raise if an INIT names a value its ActionType derives."""

    named = command.writes.keys() & action.derives.keys()
    if named:
        raise ValueError(
            f"{action.name} derives {sorted(named)}, not the command"
        )


def _check_derivations(init: _Init, pack: LoadedPack) -> None:
    """Raise if a legal INIT has a derivation with no fitting answer."""

    action = init.action

    # The clauses have passed, so every endpoint exists and none is sealed. A
    # derivation still unanswered has a `via` naming no link, a recipe that
    # cannot work, or a read `derivation_reads` omits: the pack's bug, and an
    # entity missing the value would break later reads.
    unanswered = (action.derives.keys() | action.copied_links.keys()) - (
        init.derived.keys() | init.copied.keys()
    )
    if unanswered:
        raise LookupError(f"{action.name} cannot derive {sorted(unanswered)}")

    # The pack chose these values, so no command is to blame for a bad one.
    relations = pack.entity_types[action.referent_type].relations
    unfit = [
        relation
        for relation, value in init.derived.items()
        if not _fits(relations, relation, value)
    ]
    if unfit:
        raise ValueError(f"{action.name} derives unfit {sorted(unfit)}")


def _written_value(
    command: MutateCommand | AgreeingDoubleDisclosureCommand,
    action: MutateAction,
) -> ValueClass:
    """The value a MUTATE writes: its status action's, else the command's."""

    # Its value is always named, so it never leaves one for the action to fix.
    if (
        isinstance(command, AgreeingDoubleDisclosureCommand)
        and action.fixes is not None
    ):
        raise TypeError(
            f"a double disclosure cannot take status action {action.name}"
        )

    if action.fixes is not None and command.value is None:
        return action.fixes
    if action.fixes is None and command.value is not None:
        return command.value

    # Like a command of the wrong shape: a status action's value is fixed, and
    # any other MUTATE must name one.
    raise TypeError(f"{action.name} needs a value iff it fixes none")


def _passes(entry: Entry, gate: Gate) -> bool:
    """Whether the entity holds every relation gated, admitted or contested."""

    # A gate cannot judge a conflict. The pack lists what gates read, so
    # sealing refuses the command instead.
    return judge_gate(entry, gate) is not Verdict.FAIL


def _filter_verdict(
    command: InitCommand,
    link: str,
    entry: Entry,
    registry: Registry,
    pack: LoadedPack,
) -> Verdict:
    """The verdict of the filter named for the link on its endpoint, if any."""

    name = command.filters.get(link)
    if name is None:
        return Verdict.PASS

    return judge(pack.role_filters[name], entry, registry, pack)


def _disclosures(
    event: Event,
    entity: NodeId,
    stated: Mapping[str, ValueClass | Link],
    source: str,
    allocator: IdAllocator,
) -> tuple[Disclosure, ...]:
    """One disclosure per value or link the event writes, framed by it."""

    return tuple(
        Disclosure(
            session=event.session,
            source=source,
            action_type=event.action_type,
            initiator=event.initiator,
            entity=entity,
            relation=relation,
            value=value,
            node_id=allocator.allocate(),
        )
        for relation, value in stated.items()
    )


def _readable(current: WorldValue) -> ValueClass:
    """The value a READ states, which a conflict, having no truth, is not."""

    # A READ of an entity holding a conflict is refused as sealed, so the
    # values it states are never contested.
    assert not isinstance(current, Contested)

    return current
