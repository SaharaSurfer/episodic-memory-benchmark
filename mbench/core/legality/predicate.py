from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum

from mbench.core.folds.registry import Registry
from mbench.core.records.commands import InitCommand, MutateCommand
from mbench.core.records.ids import IdAllocator, NodeId
from mbench.core.records.log import (
    Disclosure,
    Event,
    InitEvent,
    MutateEvent,
    Record,
)
from mbench.core.values.protocol import ValueClass
from mbench.packs.spec import InitAction, LoadedPack, MutateAction


class Reason(Enum):
    """Why a command was refused, a stable code the refusals are counted by."""

    INVALID_VALUE = "invalid_value"


@dataclass(frozen=True)
class Refusal:
    """A refused command: the first clause it fails, and why."""

    clause: int
    reason: Reason


type Command = InitCommand | MutateCommand


def decide(
    command: Command,
    registry: Registry,
    pack: LoadedPack,
    allocator: IdAllocator,
) -> tuple[Record, ...] | Refusal:
    """The records an accepted command produces, or why it is refused."""

    writes = _writes(command, pack)

    refusal = refuse_invalid_values(command, writes, pack)
    if refusal is not None:
        return refusal

    if isinstance(command, InitCommand):
        return _init_records(command, allocator)

    return _mutate_records(command, writes, allocator)


def refuse_invalid_values(
    command: Command, writes: Mapping[str, ValueClass], pack: LoadedPack
) -> Refusal | None:
    """Refuse a value its relation's class does not hold, or holds invalid."""

    action = pack.action_types[command.action_type]
    relations = pack.entity_types[action.referent_type].relations

    for relation, value in writes.items():
        cls = relations.get(relation)
        if cls is None or not isinstance(value, cls) or not value.is_valid():
            return Refusal(3, Reason.INVALID_VALUE)

    return None


def _writes(command: Command, pack: LoadedPack) -> Mapping[str, ValueClass]:
    """The relation-to-value map the command's event will write."""

    action = pack.action_types[command.action_type]
    if isinstance(command, InitCommand) and isinstance(action, InitAction):
        return command.writes
    if isinstance(command, MutateCommand) and isinstance(action, MutateAction):
        return {action.relation: command.value}

    # A command naming an ActionType of the other shape is a caller's bug,
    # raised like an unknown name, not a refusal a clause would count.
    raise TypeError(f"{type(command).__name__} cannot take {action.name}")


def _init_records(
    command: InitCommand, allocator: IdAllocator
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
        *_disclosures(event, event.new_id, command.source, allocator),
    )


def _mutate_records(
    command: MutateCommand,
    writes: Mapping[str, ValueClass],
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
        *_disclosures(event, event.referent, command.source, allocator),
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
