import ast
from collections.abc import Callable
from pathlib import Path

import pytest

from mbench.core.folds.registry import Registry, fold_world
from mbench.core.legality.predicate import Reason, Refusal, check
from mbench.core.records.commands import Command
from mbench.core.records.ids import NodeId
from mbench.core.records.log import AcceptedCommand, Disclosure, MutateEvent
from tests.core.world import (
    OPENED_IN,
    World,
    change_fee,
    issue,
    open_account,
    read,
    reprice,
)
from tests.testpack.pack import LOADED_PACK
from tests.testpack.values import LastFour

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "mbench"
MISSING = NodeId("zzzzz")
_OTHER_LAST_FOUR = LastFour("8203")


def _registry(world: World) -> Registry:
    return fold_world(world.records, LOADED_PACK)


@pytest.mark.parametrize(
    "command",
    [
        lambda _: open_account(2, lastFour=_OTHER_LAST_FOUR),
        lambda account: issue(account, 2),
        lambda account: change_fee(account, 2, "0"),
        lambda account: read(account, 2),
    ],
    ids=["init", "init with a link", "mutate", "read"],
)
def test_the_check_finds_nothing_against_a_legal_command(
    command: Callable[[NodeId], Command],
) -> None:
    world = World()
    account = world.open()

    assert check(command(account), _registry(world), LOADED_PACK) is None


@pytest.mark.parametrize(
    ("command", "refusal"),
    [
        (
            lambda _: open_account(2),
            Refusal(7, Reason.ANCHOR_SAME_ZONE),
        ),
        (
            lambda _: issue(MISSING, 2),
            Refusal(1, Reason.ENDPOINT_MISSING),
        ),
        (
            lambda account: reprice(account, OPENED_IN, "3.90"),
            Refusal(2, Reason.PAIR_ALREADY_WRITTEN),
        ),
        (
            lambda _: read(MISSING, 2),
            Refusal(1, Reason.REFERENT_MISSING),
        ),
    ],
    ids=["init", "init with a link", "mutate", "read"],
)
def test_the_check_gives_the_refusal_of_an_illegal_command(
    command: Callable[[NodeId], Command], refusal: Refusal
) -> None:
    world = World()
    account = world.open()

    assert check(command(account), _registry(world), LOADED_PACK) == refusal


def test_decide_pairs_an_accepted_command_with_its_records() -> None:
    world = World()
    account = world.open()
    command = change_fee(account, 2, "0")

    outcome = world.decide(command)

    assert isinstance(outcome, AcceptedCommand)
    assert outcome.command == command
    assert [type(record) for record in outcome.records] == [
        MutateEvent,
        Disclosure,
    ]


def _names_accepted_command(called: ast.expr) -> bool:
    if isinstance(called, ast.Attribute):
        return called.attr == "AcceptedCommand"

    return isinstance(called, ast.Name) and called.id == "AcceptedCommand"


def _statements_making_an_accepted_command(root: Path) -> list[str]:
    makers: list[str] = []

    for path in sorted(root.rglob("*.py")):
        for statement in ast.parse(path.read_text()).body:
            calls = (
                node.func
                for node in ast.walk(statement)
                if isinstance(node, ast.Call)
            )
            if any(_names_accepted_command(call) for call in calls):
                name = getattr(statement, "name", "<module>")
                makers.append(f"{path.relative_to(root)}:{name}")

    return makers


def test_only_decide_makes_an_accepted_command() -> None:
    assert _statements_making_an_accepted_command(PACKAGE_ROOT) == [
        "core/legality/predicate.py:decide"
    ]
