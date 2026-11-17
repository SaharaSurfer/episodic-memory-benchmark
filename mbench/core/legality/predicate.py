from dataclasses import dataclass
from enum import Enum

from mbench.core.folds.registry import Registry
from mbench.core.records.commands import InitCommand
from mbench.core.records.ids import IdAllocator
from mbench.core.records.log import Disclosure, InitEvent, Record
from mbench.packs.spec import LoadedPack


class Reason(Enum):
    """Why a command was refused, a stable code the refusals are counted by."""

    INVALID_VALUE = "invalid_value"


@dataclass(frozen=True)
class Refusal:
    """A refused command: the first clause it fails, and why."""

    clause: int
    reason: Reason


type Command = InitCommand


def decide(
    command: Command,
    registry: Registry,
    pack: LoadedPack,
    allocator: IdAllocator,
) -> tuple[Record, ...] | Refusal:
    """The records an accepted command produces, or why it is refused."""

    refusal = refuse_invalid_values(command, pack)
    if refusal is not None:
        return refusal

    return _init_records(command, allocator)


def refuse_invalid_values(command: Command, pack: LoadedPack) -> Refusal | None:
    """Refuse a value its relation's class does not hold, or holds invalid."""

    action = pack.action_types[command.action_type]
    relations = pack.entity_types[action.creates].relations

    for relation, value in command.writes.items():
        cls = relations.get(relation)
        if cls is None or not isinstance(value, cls) or not value.is_valid():
            return Refusal(3, Reason.INVALID_VALUE)

    return None


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
    disclosures = tuple(
        Disclosure(
            session=event.session,
            source=command.source,
            action_type=event.action_type,
            initiator=event.initiator,
            entity=event.new_id,
            relation=relation,
            value=value,
            node_id=allocator.allocate(),
        )
        for relation, value in event.writes.items()
    )

    return (event, *disclosures)
