from collections.abc import Callable
from dataclasses import replace
from decimal import Decimal

import pytest

from mbench.core.folds.graph import fold_trace
from mbench.core.folds.registry import fold_world
from mbench.core.legality.predicate import Reason, Refusal
from mbench.core.legality.replay import IllegalPosition, replay
from mbench.core.records.commands import Command
from mbench.core.records.ids import IdAllocator, NodeId
from mbench.core.records.log import AcceptedCommand, Link, Log
from mbench.core.values.protocol import ValueClass
from mbench.packs.spec import LoadedPack
from tests.core.world import (
    BANK_MAY_CLOSE,
    CARD_LINK,
    FEE,
    MISSING,
    WRITES,
    World,
    change_fee,
    contest,
    disclosures_in,
    issue,
    move,
    read,
    reprice,
    status_contest,
)
from tests.testpack.pack import LOADED_PACK, NO_LIVE_CARD
from tests.testpack.values import (
    CLOSED,
    FROZEN,
    InterestRate,
    MonetaryAmount,
)

FREEZE = "FREEZE_DEPOSIT_ACCOUNT"
RATE = "hasInterestRate"
UNTRUE = Refusal(4, Reason.UNTRUE_DISCLOSURE)
UNHELD_FEE = MonetaryAmount(Decimal("99"))
UNHELD_RATE = InterestRate(Decimal("9.99"))

type MakeCommand = Callable[[NodeId], Command]


def _legal_now(world: World, command: Command) -> AcceptedCommand:
    outcome = world.decide(command)
    assert isinstance(outcome, AcceptedCommand)

    return outcome


def _inserted(log: Log, position: int, accepted: AcceptedCommand) -> Log:
    commands = log.accepted

    return Log().append((*commands[:position], accepted, *commands[position:]))


def test_an_empty_log_replays_clean() -> None:
    assert replay(Log(), LOADED_PACK) is None


@pytest.mark.parametrize(
    ("pack", "earlier", "later", "refusal"),
    [
        (
            LOADED_PACK,
            lambda account: move(account, 2, FREEZE),
            lambda account: move(account, 3, FREEZE),
            Refusal(1, Reason.GATE_FAILED),
        ),
        (
            LOADED_PACK,
            lambda account: issue(account, 2),
            lambda account: replace(
                issue(account, 3), filters={CARD_LINK: NO_LIVE_CARD}
            ),
            Refusal(1, Reason.ENDPOINT_FILTER_FAILED),
        ),
        (
            LOADED_PACK,
            lambda account: change_fee(account, 2, "1"),
            lambda account: change_fee(account, 2, "0"),
            Refusal(2, Reason.PAIR_ALREADY_WRITTEN),
        ),
        (
            LOADED_PACK,
            lambda account: contest(account, 2, "3.90", "3.80"),
            lambda account: reprice(account, 3, "3.70"),
            Refusal(6, Reason.PAIR_SEALED),
        ),
        (
            BANK_MAY_CLOSE,
            lambda account: status_contest(account, 2, FROZEN, CLOSED),
            lambda account: change_fee(account, 3, "0"),
            Refusal(6, Reason.ENTITY_SEALED),
        ),
        (
            LOADED_PACK,
            lambda account: reprice(account, 2, "3.90"),
            lambda account: reprice(account, 3, "3.90"),
            Refusal(8, Reason.UNCHANGED_VALUE),
        ),
        (
            LOADED_PACK,
            lambda account: change_fee(account, 2, "0"),
            lambda account: read(account, 3),
            UNTRUE,
        ),
    ],
    ids=[
        "gate",
        "role filter",
        "second write",
        "sealed pair",
        "sealed entity",
        "unchanged value",
        "top-up before a read of its pair",
    ],
)
def test_an_earlier_command_breaking_a_later_one_is_reported_there(
    pack: LoadedPack,
    earlier: MakeCommand,
    later: MakeCommand,
    refusal: Refusal,
) -> None:
    world = World(pack)
    account = world.open()
    inserted = _legal_now(world, earlier(account))
    world.accept(later(account))

    log = _inserted(world.log, 1, inserted)

    assert replay(log, pack) == IllegalPosition(2, refusal)


def test_only_the_first_illegal_position_is_reported() -> None:
    world = World()
    account = world.open()
    top_up = _legal_now(world, change_fee(account, 2, "0"))
    world.accept(read(account, 3))
    world.accept(read(account, 4))

    log = _inserted(world.log, 1, top_up)

    assert replay(log, world.pack) == IllegalPosition(2, UNTRUE)


def _with_last_disclosure_of(
    accepted: AcceptedCommand, relation: str, value: ValueClass | Link
) -> AcceptedCommand:
    target = [
        disclosure
        for disclosure in disclosures_in(accepted.records)
        if disclosure.relation == relation
    ][-1]
    untrue = replace(target, value=value)
    records = tuple(
        untrue if record is target else record for record in accepted.records
    )

    return replace(accepted, records=records)


@pytest.mark.parametrize(
    ("command", "relation", "value"),
    [
        (lambda account: issue(account, 2), CARD_LINK, Link(MISSING)),
        (lambda account: change_fee(account, 2, "0"), FEE, UNHELD_FEE),
        (
            lambda account: contest(account, 2, "3.90", "3.80"),
            RATE,
            UNHELD_RATE,
        ),
        (lambda account: read(account, 2), FEE, UNHELD_FEE),
    ],
    ids=["init link", "mutate", "second of a conflict", "read"],
)
def test_every_stored_disclosure_must_state_the_world(
    command: MakeCommand, relation: str, value: ValueClass | Link
) -> None:
    world = World()
    account = world.open()
    accepted = _legal_now(world, command(account))

    log = world.log.append(
        [_with_last_disclosure_of(accepted, relation, value)]
    )

    assert replay(log, world.pack) == IllegalPosition(1, UNTRUE)


def test_a_disclosure_cannot_state_the_value_its_own_event_replaced() -> None:
    world = World()
    account = world.open()
    accepted = _legal_now(world, change_fee(account, 2, "0"))

    log = world.log.append(
        [_with_last_disclosure_of(accepted, FEE, WRITES[FEE])]
    )

    assert replay(log, world.pack) == IllegalPosition(1, UNTRUE)


def test_replay_draws_no_id(monkeypatch: pytest.MonkeyPatch) -> None:
    world = World()
    account = world.open()
    world.accept(change_fee(account, 2, "0"))
    world.accept(read(account, 3))

    def refuse_to_draw(_: IdAllocator) -> NodeId:
        raise AssertionError("replay drew an id")

    monkeypatch.setattr(IdAllocator, "allocate", refuse_to_draw)

    assert replay(world.log, world.pack) is None


def test_the_folds_accept_a_log_replay_finds_illegal() -> None:
    world = World()
    account = world.open()
    inserted = _legal_now(world, change_fee(account, 2, "1"))
    world.accept(change_fee(account, 2, "0"))

    log = _inserted(world.log, 1, inserted)
    entry = fold_world(log.records, world.pack).entry(account)
    graph = fold_trace(log.records, world.pack)

    assert replay(log, world.pack) is not None
    assert entry is not None
    assert entry.values[FEE].value == MonetaryAmount(Decimal("0"))
    assert {node.id for node in graph.entity_nodes()} == {account}
