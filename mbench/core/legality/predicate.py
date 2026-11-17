from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum

from mbench.core.folds.registry import Entry, Registry, Stamped, is_live
from mbench.core.records.commands import (
    InitCommand,
    MutateCommand,
    ReadCommand,
)
from mbench.core.records.ids import IdAllocator, NodeId
from mbench.core.records.log import (
    READ,
    Disclosure,
    Event,
    InitEvent,
    MutateEvent,
    Record,
)
from mbench.core.values.protocol import ValueClass
from mbench.packs.spec import (
    Gate,
    InitAction,
    LoadedPack,
    MutateAction,
    SourceKind,
)


class Reason(Enum):
    """Why a command was refused, a stable code the refusals are counted by."""

    REFERENT_MISSING = "referent_missing"
    REFERENT_WRONG_TYPE = "referent_wrong_type"
    GATE_FAILED = "gate_failed"
    NOT_LIVE = "not_live"
    PAIR_ALREADY_WRITTEN = "pair_already_written"
    INVALID_VALUE = "invalid_value"
    UNTRUE_DISCLOSURE = "untrue_disclosure"
    UNCHANGED_VALUE = "unchanged_value"


@dataclass(frozen=True)
class Refusal:
    """A refused command: the first clause it fails, and why."""

    clause: int
    reason: Reason


type EventCommand = InitCommand | MutateCommand
type Command = EventCommand | ReadCommand


def decide(
    command: Command,
    registry: Registry,
    pack: LoadedPack,
    allocator: IdAllocator,
) -> tuple[Record, ...] | Refusal:
    """The records an accepted command produces, or why it is refused."""

    if isinstance(command, ReadCommand):
        return _decide_read(command, registry, allocator)

    writes = _writes(command, pack)

    refusal = (
        refuse_unfit_referent(command, registry, pack)
        or refuse_second_write(command, writes, registry)
        or refuse_invalid_values(command, writes, pack)
        or refuse_unchanged_value(command, writes, registry)
    )
    if refusal is not None:
        return refusal

    source = default_source(command, pack)
    if isinstance(command, InitCommand):
        return _init_records(command, source, allocator)

    return _mutate_records(command, writes, source, allocator)


def default_source(command: EventCommand, pack: LoadedPack) -> str:
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

    # An INIT has no referent, its link endpoints have none to check yet.
    if not isinstance(command, MutateCommand):
        return None

    action = pack.action_types[command.action_type]
    entry = registry.entry(command.referent)

    if entry is None:
        return Refusal(1, Reason.REFERENT_MISSING)
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


def refuse_missing_entity(
    command: ReadCommand, registry: Registry
) -> Refusal | None:
    """Refuse a READ of an entity the world does not hold."""

    if registry.entry(command.entity) is None:
        return Refusal(1, Reason.REFERENT_MISSING)

    return None


def refuse_second_write(
    command: EventCommand, writes: Mapping[str, ValueClass], registry: Registry
) -> Refusal | None:
    """Refuse a write to a pair already written in the command's session."""

    for current in _current(command, writes, registry).values():
        if current.session == command.session:
            return Refusal(2, Reason.PAIR_ALREADY_WRITTEN)

    return None


def refuse_invalid_values(
    command: EventCommand, writes: Mapping[str, ValueClass], pack: LoadedPack
) -> Refusal | None:
    """Refuse a value its relation's class does not hold, or holds invalid."""

    action = pack.action_types[command.action_type]
    relations = pack.entity_types[action.referent_type].relations

    for relation, value in writes.items():
        cls = relations.get(relation)
        if cls is None or not isinstance(value, cls) or not value.is_valid():
            return Refusal(3, Reason.INVALID_VALUE)

    return None


def refuse_unchanged_value(
    command: EventCommand, writes: Mapping[str, ValueClass], registry: Registry
) -> Refusal | None:
    """Refuse a write of the value its pair already holds."""

    for relation, current in _current(command, writes, registry).items():
        if writes[relation] == current.value:
            return Refusal(8, Reason.UNCHANGED_VALUE)

    return None


def refuse_untrue_disclosure(
    disclosure: Disclosure, registry: Registry
) -> Refusal | None:
    """Refuse a disclosure of a value the world does not currently hold."""

    entry = registry.entry(disclosure.entity)
    current = None if entry is None else entry.values.get(disclosure.relation)

    if current is None or not admits(current.value, disclosure.value):
        return Refusal(4, Reason.UNTRUE_DISCLOSURE)

    return None


def admits(current: ValueClass, stated: ValueClass) -> bool:
    """Whether a pair holding the current value may be said to hold another."""

    return stated == current


def _current(
    command: EventCommand, writes: Mapping[str, ValueClass], registry: Registry
) -> Mapping[str, Stamped]:
    """The current stamped value of each pair the command writes, if any."""

    # An INIT writes a new entity, whose pairs hold nothing yet. A referent
    # the registry lacks is the referent clause's to refuse, not these.
    if not isinstance(command, MutateCommand):
        return {}

    entry = registry.entry(command.referent)
    if entry is None:
        return {}

    return {
        relation: entry.values[relation]
        for relation in writes
        if relation in entry.values
    }


def _writes(
    command: EventCommand, pack: LoadedPack
) -> Mapping[str, ValueClass]:
    """The relation-to-value map the command's event will write."""

    action = pack.action_types[command.action_type]
    if isinstance(command, InitCommand) and isinstance(action, InitAction):
        return command.writes
    if isinstance(command, MutateCommand) and isinstance(action, MutateAction):
        return {action.relation: _written_value(command, action)}

    # A command naming an ActionType of the other shape is a caller's bug,
    # raised like an unknown name, not a refusal a clause would count.
    raise TypeError(f"{type(command).__name__} cannot take {action.name}")


def _written_value(command: MutateCommand, action: MutateAction) -> ValueClass:
    """The value a MUTATE writes: its status action's, else the command's."""

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


def _init_records(
    command: InitCommand, source: str, allocator: IdAllocator
) -> tuple[Record, ...]:
    """The INIT event, then one default disclosure per value it writes."""

    event = InitEvent(
        session=command.session,
        initiator=command.initiator,
        action_type=command.action_type,
        new_id=allocator.allocate(),
        writes=command.writes,
    )

    return (
        event,
        *_disclosures(event, event.new_id, source, allocator),
    )


def _mutate_records(
    command: MutateCommand,
    writes: Mapping[str, ValueClass],
    source: str,
    allocator: IdAllocator,
) -> tuple[Record, ...]:
    """The MUTATE event, then the default disclosure of its one value."""

    event = MutateEvent(
        session=command.session,
        initiator=command.initiator,
        action_type=command.action_type,
        referent=command.referent,
        writes=writes,
    )

    return (
        event,
        *_disclosures(event, event.referent, source, allocator),
    )


def _disclosures(
    event: Event, entity: NodeId, source: str, allocator: IdAllocator
) -> tuple[Disclosure, ...]:
    """One disclosure per value the event writes, framed by the event."""

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
        for relation, value in event.writes.items()
    )


def _decide_read(
    command: ReadCommand, registry: Registry, allocator: IdAllocator
) -> tuple[Record, ...] | Refusal:
    """The READ's disclosures of the entity's current values, or a refusal."""

    refusal = refuse_missing_entity(command, registry)
    if refusal is not None:
        return refusal

    # Each value is copied from the registry, so these disclosures always
    # pass `refuse_untrue_disclosure`, only a disclosure written by other
    # means, as in a stored log, can fail it.
    entry = registry.entry(command.entity)
    assert entry is not None

    return tuple(
        Disclosure(
            session=command.session,
            source=command.source,
            action_type=READ,
            initiator=command.initiator,
            entity=command.entity,
            relation=relation,
            value=current.value,
            node_id=allocator.allocate(),
        )
        for relation, current in entry.values.items()
    )
