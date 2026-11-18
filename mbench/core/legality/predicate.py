from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum

from mbench.core.folds.registry import Entry, Registry, Stamped, is_live
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
    Gate,
    InitAction,
    Linker,
    LoadedPack,
    MutateAction,
    RoleFilter,
    SourceKind,
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
    ANCHOR_SAME_ZONE = "anchor_same_zone"
    UNCHANGED_VALUE = "unchanged_value"


@dataclass(frozen=True)
class Refusal:
    """A refused command: the first clause it fails, and why."""

    clause: int
    reason: Reason


def decide(
    command: Command,
    registry: Registry,
    pack: LoadedPack,
    allocator: IdAllocator,
) -> AcceptedCommand | Refusal:
    """The command with the records it produces, or why it is refused."""

    refusal = check(command, registry, pack)
    if refusal is not None:
        return refusal

    records = _build_records(command, registry, pack, allocator)

    return AcceptedCommand(command, records)


def check(
    command: Command, registry: Registry, pack: LoadedPack
) -> Refusal | None:
    """Why the command is illegal at this registry, if it is."""

    if isinstance(command, ReadCommand):
        return refuse_missing_entity(command, registry)

    writes = _world_writes(command, pack)
    _check_links(command, pack)
    _check_sources(command, pack)

    return (
        refuse_unfit_referent(command, registry, pack)
        or refuse_unfit_endpoints(command, registry, pack)
        or refuse_second_write(command, writes, registry)
        or refuse_invalid_values(command, registry, pack)
        or refuse_illegal_contest(command, registry, pack)
        or refuse_anchor_same_zone(command, registry, pack)
        or refuse_unchanged_value(command, writes, registry)
    )


def _build_records(
    command: Command,
    registry: Registry,
    pack: LoadedPack,
    allocator: IdAllocator,
) -> tuple[Record, ...]:
    """The records of a command the check has passed, drawing their ids."""

    if isinstance(command, ReadCommand):
        return _read_records(command, registry, allocator)
    if isinstance(command, ConflictingDoubleDisclosureCommand):
        return _contest_records(command, registry, pack, allocator)
    if isinstance(command, AgreeingDoubleDisclosureCommand):
        return _mutate_records(
            command, _plain_writes(command, pack), command.sources, allocator
        )

    source = default_source(command, pack)
    if isinstance(command, InitCommand):
        return _init_records(command, source, allocator)

    return _mutate_records(
        command, _plain_writes(command, pack), (source,), allocator
    )


def default_source(
    command: InitCommand | MutateCommand, pack: LoadedPack
) -> str:
    """The source named, else the initiator's speaker, else a document."""

    if command.source is not None:
        return command.source

    for speaker in pack.speakers.values():
        if speaker.represents == command.initiator:
            return speaker.id

    # Any document will do, the first declared keeps a replay stable.
    for source in pack.sources.values():
        if source.kind is SourceKind.DOCUMENT:
            return source.id

    # An off-stage actor in a pack with no document is the pack's bug, not a
    # refusal a clause would count.
    raise LookupError(f"no source can state an event of {command.initiator}")


def refuse_unfit_referent(
    command: EventCommand, registry: Registry, pack: LoadedPack
) -> Refusal | None:
    """Refuse a MUTATE on a missing, mistyped, gated-out or dead referent."""

    # An INIT has no referent, only link endpoints, checked on their own.
    if isinstance(command, InitCommand):
        return None

    entry = registry.entry(command.referent)
    if entry is None:
        return Refusal(1, Reason.REFERENT_MISSING)

    # It names no ActionType, so it has no referent type or gate of its own.
    if isinstance(command, ConflictingDoubleDisclosureCommand):
        return None if is_live(entry, pack) else Refusal(1, Reason.NOT_LIVE)

    action = pack.action_types[command.action_type]
    if entry.type != action.referent_type:
        return Refusal(1, Reason.REFERENT_WRONG_TYPE)

    gate = action.gate if isinstance(action, MutateAction) else {}
    if not _passes(entry, gate):
        return Refusal(1, Reason.GATE_FAILED)

    # A gate that reads the status has named the statuses it admits, a
    # terminal one included, so it, not liveness, decides.
    status = pack.entity_types[entry.type].status
    if status not in gate and not is_live(entry, pack):
        return Refusal(1, Reason.NOT_LIVE)

    return None


def refuse_unfit_endpoints(
    command: EventCommand, registry: Registry, pack: LoadedPack
) -> Refusal | None:
    """Refuse an INIT whose endpoint is missing, mistyped, gated or filtered."""

    if not isinstance(command, InitCommand):
        return None

    action = _init_action(command, pack)
    targets = pack.entity_types[action.referent_type].links

    # An endpoint need not be live: a replacement points at the closed card
    # it replaces. A gate or filter that wants a live one says so.
    for link, endpoint in command.links.items():
        entry = registry.entry(endpoint)

        if entry is None:
            return Refusal(1, Reason.ENDPOINT_MISSING)
        if entry.type not in targets[link]:
            return Refusal(1, Reason.ENDPOINT_WRONG_TYPE)
        if not _passes(entry, action.links[link]):
            return Refusal(1, Reason.ENDPOINT_GATE_FAILED)
        filter_name = command.filters.get(link)
        if filter_name is not None and not _passes_filter(
            entry, pack.role_filters[filter_name], registry, pack
        ):
            return Refusal(1, Reason.ENDPOINT_FILTER_FAILED)

    return None


def refuse_missing_entity(
    command: ReadCommand, registry: Registry
) -> Refusal | None:
    """Refuse a READ of an entity the world does not hold."""

    if registry.entry(command.entity) is None:
        return Refusal(1, Reason.REFERENT_MISSING)

    return None


def refuse_second_write(
    command: EventCommand, writes: Mapping[str, WorldValue], registry: Registry
) -> Refusal | None:
    """Refuse a write to a pair already written in the command's session."""

    for current in _current(command, writes, registry).values():
        if current.session == command.session:
            return Refusal(2, Reason.PAIR_ALREADY_WRITTEN)

    return None


def refuse_invalid_values(
    command: EventCommand, registry: Registry, pack: LoadedPack
) -> Refusal | None:
    """Refuse a value its relation's class does not hold, or holds invalid."""

    entity_type = _written_type(command, registry, pack)
    relations = pack.entity_types[entity_type].relations

    for relation, value in _stated_values(command, pack):
        cls = relations.get(relation)
        if cls is None or not isinstance(value, cls) or not value.is_valid():
            return Refusal(3, Reason.INVALID_VALUE)

    return None


def refuse_illegal_contest(
    command: EventCommand, registry: Registry, pack: LoadedPack
) -> Refusal | None:
    """Refuse a contested write its sources, values or writers do not allow."""

    if not isinstance(command, ConflictingDoubleDisclosureCommand):
        return None

    entry = registry.entry(command.referent)
    # The referent clause runs first and has refused a missing referent.
    assert entry is not None

    return (
        _refuse_contest_sources(command, pack)
        or _refuse_contest_values(command, entry)
        or _refuse_contest_writers(command, entry, pack)
    )


def _refuse_contest_values(
    command: ConflictingDoubleDisclosureCommand, entry: Entry
) -> Refusal | None:
    """Refuse two equal values, or one the pair already holds."""

    if command.a == command.b:
        return Refusal(5, Reason.CONTESTED_VALUES_EQUAL)

    # Only the current value: the registry keeps no earlier versions, so
    # whoever draws the two values must avoid those.
    current = entry.values.get(command.relation)
    if current is not None and current.value in (command.a, command.b):
        return Refusal(5, Reason.CONTESTED_VALUE_IS_CURRENT)

    return None


def _refuse_contest_writers(
    command: ConflictingDoubleDisclosureCommand,
    entry: Entry,
    pack: LoadedPack,
) -> Refusal | None:
    """Refuse values no pair of unstated, co-initiated ActionTypes writes."""

    # Nothing can write from a conflict, but that is not why a pair already
    # contested stays closed, so this clause does not give the refusal.
    current = entry.values.get(command.relation)
    if current is not None and isinstance(current.value, Contested):
        return None

    writers = []
    for value in (command.a, command.b):
        writer = _find_writer(entry, command.relation, value, pack)
        if writer is None:
            return Refusal(5, Reason.NO_WRITER)
        if not _passes(entry, writer.gate):
            return Refusal(5, Reason.WRITER_GATE_FAILED)
        if not pack.passes_owner_rule(writer.name):
            return Refusal(5, Reason.NO_CONTESTABLE_FRAMING)
        writers.append(writer.name)

    # The command names the initiator, since two framings may share several.
    first, second = writers
    if command.initiator not in pack.shared_initiators(first, second):
        return Refusal(5, Reason.INITIATOR_NOT_SHARED)

    return None


def _refuse_contest_sources(
    command: ConflictingDoubleDisclosureCommand, pack: LoadedPack
) -> Refusal | None:
    """Refuse sources of unequal authority, or one speaker named twice."""

    first, second = (pack.sources[source] for source in command.sources)

    if first.authority != second.authority:
        return Refusal(5, Reason.UNEQUAL_AUTHORITY)

    # Two letters are two messages, one person giving two figures is a
    # self-correction.
    if first.id == second.id and first.kind is SourceKind.SPEAKER:
        return Refusal(5, Reason.SPEAKER_TWICE)

    return None


def refuse_anchor_same_zone(
    command: EventCommand, registry: Registry, pack: LoadedPack
) -> Refusal | None:
    """Refuse an INIT whose anchor is in the same zone as one of its type's."""

    if not isinstance(command, InitCommand):
        return None

    entity_type = pack.entity_types[_init_action(command, pack).referent_type]
    if not entity_type.anchor:
        return None

    # Closed entities count too: a question may name one, so its anchor
    # must still pick it out alone.
    for entry in registry.entries():
        if entry.type == entity_type.name and all(
            _same_part(command.writes, entry, part)
            for part in entity_type.anchor
        ):
            return Refusal(7, Reason.ANCHOR_SAME_ZONE)

    return None


def refuse_unchanged_value(
    command: EventCommand, writes: Mapping[str, WorldValue], registry: Registry
) -> Refusal | None:
    """Refuse a write of the value its pair already holds."""

    for relation, current in _current(command, writes, registry).items():
        if writes[relation] == current.value:
            return Refusal(8, Reason.UNCHANGED_VALUE)

    return None


def refuse_untrue_disclosure(
    disclosure: Disclosure, registry: Registry
) -> Refusal | None:
    """Refuse a disclosure of a value or link the world does not hold."""

    entry = registry.entry(disclosure.entity)
    if entry is None:
        return Refusal(4, Reason.UNTRUE_DISCLOSURE)

    if isinstance(disclosure.value, Link):
        holds = entry.links.get(disclosure.relation) == disclosure.value.target
    else:
        current = entry.values.get(disclosure.relation)
        holds = current is not None and admits(current.value, disclosure.value)

    return None if holds else Refusal(4, Reason.UNTRUE_DISCLOSURE)


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


def admits(current: WorldValue, stated: ValueClass) -> bool:
    """Whether a pair holding the current value may be said to hold another."""

    if isinstance(current, Contested):
        return stated in current.members

    return stated == current


def _current(
    command: EventCommand, writes: Mapping[str, WorldValue], registry: Registry
) -> Mapping[str, Stamped]:
    """The current stamped value of each pair the command writes, if any."""

    # An INIT writes a new entity, whose pairs hold nothing yet.
    if isinstance(command, InitCommand):
        return {}

    entry = registry.entry(command.referent)
    # The referent clause runs first and has refused a missing referent.
    assert entry is not None

    return {
        relation: entry.values[relation]
        for relation in writes
        if relation in entry.values
    }


def _written_type(
    command: EventCommand, registry: Registry, pack: LoadedPack
) -> str:
    """The type of the entity the command writes to."""

    if isinstance(command, ConflictingDoubleDisclosureCommand):
        entry = registry.entry(command.referent)
        # The referent clause runs first and has refused a missing referent.
        assert entry is not None
        return entry.type

    return pack.action_types[command.action_type].referent_type


def _world_writes(
    command: EventCommand, pack: LoadedPack
) -> Mapping[str, WorldValue]:
    """The relation-to-value map the command's event will write."""

    if isinstance(command, ConflictingDoubleDisclosureCommand):
        return {command.relation: Contested(command.a, command.b)}

    return _plain_writes(command, pack)


def _stated_values(
    command: EventCommand, pack: LoadedPack
) -> tuple[tuple[str, ValueClass], ...]:
    """Each relation and plain value the command puts into the world."""

    if isinstance(command, ConflictingDoubleDisclosureCommand):
        return (
            (command.relation, command.a),
            (command.relation, command.b),
        )

    return tuple(_plain_writes(command, pack).items())


def _plain_writes(
    command: InitCommand | MutateCommand | AgreeingDoubleDisclosureCommand,
    pack: LoadedPack,
) -> Mapping[str, ValueClass]:
    """The plain relation-to-value map a non-conflict's event will write."""

    action = pack.action_types[command.action_type]
    if isinstance(command, InitCommand) and isinstance(action, InitAction):
        return command.writes
    if not isinstance(command, InitCommand) and isinstance(
        action, MutateAction
    ):
        return {action.relation: _written_value(command, action)}

    # A command naming an ActionType of the other shape is a caller's bug,
    # raised like an unknown name, not a refusal a clause would count.
    raise TypeError(f"{type(command).__name__} cannot take {action.name}")


def _check_links(command: EventCommand, pack: LoadedPack) -> None:
    """Raise unless an INIT fills its links and names filters it can use."""

    if not isinstance(command, InitCommand):
        return

    action = _init_action(command, pack)

    # Like a command of the wrong shape: the caller fills every link the
    # INIT writes, and a link it lacks or does not write is its bug.
    if command.links.keys() != action.links.keys():
        raise ValueError(
            f"{action.name} writes links {sorted(action.links)},"
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


def _check_sources(command: EventCommand, pack: LoadedPack) -> None:
    """Raise unless a double disclosure names declared sources."""

    if not isinstance(
        command,
        AgreeingDoubleDisclosureCommand | ConflictingDoubleDisclosureCommand,
    ):
        return

    # No clause covers the sources an agreeing pair names, so a wrong pair is
    # the caller's bug, raised rather than refused. A conflict may come from
    # one document twice.
    first, second = command.sources
    if isinstance(command, AgreeingDoubleDisclosureCommand) and first == second:
        raise ValueError(f"{first} is named twice, not two different sources")

    unknown = set(command.sources) - pack.sources.keys()
    if unknown:
        raise ValueError(f"the pack declares no source {sorted(unknown)}")


def _init_action(command: InitCommand, pack: LoadedPack) -> InitAction:
    """The INIT ActionType the command names, its shape already checked."""

    action = pack.action_types[command.action_type]
    # `_writes` has raised for an INIT command naming a MUTATE ActionType.
    assert isinstance(action, InitAction)

    return action


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
    """Whether the entry holds an admitted value for every relation gated."""

    return all(
        relation in entry.values and entry.values[relation].value in admitted
        for relation, admitted in gate.items()
    )


def _passes_filter(
    entry: Entry,
    role_filter: RoleFilter,
    registry: Registry,
    pack: LoadedPack,
) -> bool:
    """Whether the entity is one the role filter lets a role bind."""

    return (
        entry.type == role_filter.entity_type
        and _passes(entry, role_filter.values)
        and (not role_filter.live or is_live(entry, pack))
        and not any(
            _has_live_linker(entry, linker, registry, pack)
            for linker in role_filter.no_live_linkers
        )
    )


def _has_live_linker(
    entry: Entry, linker: Linker, registry: Registry, pack: LoadedPack
) -> bool:
    """Whether a live entity points at the entry in the linker's way."""

    return any(
        other.type == linker.entity_type
        and other.links.get(linker.link) == entry.id
        and is_live(other, pack)
        for other in registry.entries()
    )


def _init_records(
    command: InitCommand, source: str, allocator: IdAllocator
) -> tuple[Record, ...]:
    """The INIT event, then a default disclosure per value and link."""

    event = InitEvent(
        session=command.session,
        initiator=command.initiator,
        action_type=command.action_type,
        new_id=allocator.allocate(),
        writes=command.writes,
        links=command.links,
    )

    links = {link: Link(target) for link, target in event.links.items()}

    return (
        event,
        *_disclosures(
            event, event.new_id, {**event.writes, **links}, source, allocator
        ),
    )


def _mutate_records(
    command: MutateCommand | AgreeingDoubleDisclosureCommand,
    writes: Mapping[str, ValueClass],
    sources: tuple[str, ...],
    allocator: IdAllocator,
) -> tuple[Record, ...]:
    """The MUTATE event, then one disclosure of its value per source."""

    event = MutateEvent(
        session=command.session,
        initiator=command.initiator,
        action_type=command.action_type,
        referent=command.referent,
        writes=writes,
    )

    return (
        event,
        *(
            disclosure
            for source in sources
            for disclosure in _disclosures(
                event, event.referent, writes, source, allocator
            )
        ),
    )


def _contest_records(
    command: ConflictingDoubleDisclosureCommand,
    registry: Registry,
    pack: LoadedPack,
    allocator: IdAllocator,
) -> tuple[Record, ...]:
    """The CONTEST event, then each source's disclosure of its own value."""

    entry = registry.entry(command.referent)
    # The check has refused a contested write on a missing referent.
    assert entry is not None

    event = MutateEvent(
        session=command.session,
        initiator=command.initiator,
        action_type=CONTEST,
        referent=command.referent,
        writes=_world_writes(command, pack),
    )

    return (
        event,
        *(
            Disclosure(
                session=event.session,
                source=source,
                action_type=_writer(entry, command.relation, value, pack).name,
                initiator=event.initiator,
                entity=event.referent,
                relation=command.relation,
                value=value,
                node_id=allocator.allocate(),
            )
            for source, value in zip(
                command.sources, (command.a, command.b), strict=True
            )
        ),
    )


def _writer(
    entry: Entry, relation: str, value: ValueClass, pack: LoadedPack
) -> MutateAction:
    """The ActionType that writes the value, raising if none does."""

    action = _find_writer(entry, relation, value, pack)

    # Only a pair already contested gets here, and a disclosure cannot go
    # unframed.
    if action is None:
        raise LookupError(f"no ActionType writes {value} to {relation}")

    return action


def _find_writer(
    entry: Entry, relation: str, value: ValueClass, pack: LoadedPack
) -> MutateAction | None:
    """The ActionType that would write the value over the pair's current."""

    stamped = entry.values.get(relation)
    if stamped is None or isinstance(stamped.value, Contested):
        return None

    return pack.action_for(entry.type, relation, (stamped.value, value))


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


def _read_records(
    command: ReadCommand, registry: Registry, allocator: IdAllocator
) -> tuple[Record, ...]:
    """The READ's disclosures of the entity's current values."""

    # Each value is copied from the registry, so these disclosures always
    # pass `refuse_untrue_disclosure`, only a disclosure written by other
    # means, as in a stored log, can fail it.
    entry = registry.entry(command.entity)
    # The check has refused a READ of an entity the registry lacks.
    assert entry is not None

    return tuple(
        Disclosure(
            session=command.session,
            source=command.source,
            action_type=READ,
            initiator=command.initiator,
            entity=command.entity,
            relation=relation,
            value=_readable(current.value),
            node_id=allocator.allocate(),
        )
        for relation, current in entry.values.items()
    )


def _readable(current: WorldValue) -> ValueClass:
    """The value a READ states, which a conflict, having no truth, is not."""

    # The check lets this through, but a disclosure states one plain value.
    if isinstance(current, Contested):
        raise ValueError("a contested value cannot be read")

    return current
