from typing import assert_never

from mbench.core.records.commands import (
    AgreeingDoubleDisclosureCommand,
    Command,
    ConflictingDoubleDisclosureCommand,
    EventCommand,
    InitCommand,
    MutateCommand,
    ReadCommand,
)
from mbench.packs.spec import LoadedPack


def check_names(command: Command, pack: LoadedPack) -> None:
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

    match command:
        case (
            AgreeingDoubleDisclosureCommand()
            | ConflictingDoubleDisclosureCommand()
        ):
            return command.sources
        case InitCommand() | MutateCommand() | ReadCommand():
            # None leaves the source to the default, which names a declared
            # one.
            return () if command.source is None else (command.source,)
        case _:
            assert_never(command)


def wrong_shape(command: EventCommand, action: str) -> TypeError:
    """The error for a command naming an ActionType of the other shape."""

    # A caller's bug, raised like an unknown name, not a refusal a clause
    # would count.
    return TypeError(f"{type(command).__name__} cannot take {action}")
