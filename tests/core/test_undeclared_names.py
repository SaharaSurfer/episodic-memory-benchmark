from collections.abc import Callable
from dataclasses import replace

import pytest

from mbench.core.records.commands import (
    Command,
    InitCommand,
    MutateCommand,
    ReadCommand,
)
from mbench.core.records.ids import NodeId
from tests.core.world import (
    LAST_FOURS,
    MISSING,
    World,
    agree,
    contest,
    open_account,
    read,
    reprice,
)
from tests.testpack.values import LastFour

# Each builds a command about the world's first account.
type Build = Callable[[NodeId], Command]
type BuildNamingOneSource = Callable[
    [NodeId], InitCommand | MutateCommand | ReadCommand
]

NAMING_ONE_SOURCE: dict[str, BuildNamingOneSource] = {
    # The world's first account took the first last four.
    "init": lambda _: open_account(2, lastFour=LastFour(LAST_FOURS[1])),
    "mutate": lambda account: reprice(account, 2, "4.75"),
    "read": lambda account: read(account, 2),
}

EVERY_COMMAND: dict[str, Build] = {
    **NAMING_ONE_SOURCE,
    "agree": lambda account: agree(account, 2, "4.75"),
    "contest": lambda account: contest(account, 2, "4.75", "4.80"),
}


@pytest.mark.parametrize(
    "build", NAMING_ONE_SOURCE.values(), ids=list(NAMING_ONE_SOURCE)
)
def test_a_source_the_pack_does_not_declare_raises(
    build: BuildNamingOneSource,
) -> None:
    world = World()
    account = world.open()
    command = replace(build(account), source="nobody")

    with pytest.raises(ValueError, match=r"declares no source \['nobody'\]"):
        world.decide(command)


@pytest.mark.parametrize(
    "build", EVERY_COMMAND.values(), ids=list(EVERY_COMMAND)
)
def test_an_initiator_the_pack_does_not_declare_raises(build: Build) -> None:
    world = World()
    account = world.open()
    command = replace(build(account), initiator="NOBODY")

    with pytest.raises(ValueError, match="declares no initiator NOBODY"):
        world.decide(command)


def test_a_read_of_a_missing_entity_by_an_undeclared_source_raises() -> None:
    # The name is the caller's bug, so it raises before any clause refuses.
    world = World()
    command = replace(read(MISSING, 2), source="nobody")

    with pytest.raises(ValueError, match=r"declares no source \['nobody'\]"):
        world.decide(command)
