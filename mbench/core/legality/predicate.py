from typing import assert_never

from mbench.core.folds.registry import Registry
from mbench.core.legality import _contest, _init, _mutate, _read
from mbench.core.legality._caller_bugs import check_names
from mbench.core.legality._refusal import Reason, Refusal
from mbench.core.records.commands import (
    AgreeingDoubleDisclosureCommand,
    Command,
    ConflictingDoubleDisclosureCommand,
    InitCommand,
    MutateCommand,
    ReadCommand,
)
from mbench.core.records.ids import IdAllocator
from mbench.core.records.log import AcceptedCommand, Disclosure, Link
from mbench.core.values.contested import Contested, WorldValue
from mbench.core.values.protocol import ValueClass
from mbench.packs.spec import LoadedPack

__all__ = ["Reason", "Refusal", "check", "decide", "refuse_untrue_disclosure"]


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


def _admits(current: WorldValue, stated: ValueClass) -> bool:
    """Whether a pair holding the current value may be said to hold another."""

    if isinstance(current, Contested):
        return stated in current.members

    return stated == current


type _Resolved = _read.Read | _mutate.Mutate | _contest.Contest | _init.Init


def _checked(
    command: Command, registry: Registry, pack: LoadedPack
) -> Refusal | _Resolved:
    """What the command will do, or why it is illegal at this registry."""

    check_names(command, pack)

    match command:
        case ReadCommand():
            return _read.checked(command, registry)
        case MutateCommand() | AgreeingDoubleDisclosureCommand():
            return _mutate.checked(command, registry, pack)
        case ConflictingDoubleDisclosureCommand():
            return _contest.checked(command, registry, pack)
        case InitCommand():
            return _init.checked(command, registry, pack)
        case _:
            assert_never(command)
