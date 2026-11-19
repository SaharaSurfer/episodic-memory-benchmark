from collections.abc import Callable
from dataclasses import replace
from decimal import Decimal

import pytest

from mbench.core.legality.predicate import Reason, Refusal
from mbench.core.records.commands import InitCommand, MutateCommand
from mbench.core.records.ids import NodeId
from mbench.core.records.log import AcceptedCommand, InitEvent, MutateEvent
from mbench.packs.spec import EntityType, InitAction, MutateAction
from tests.core.world import (
    MISSING,
    REPORTED_IN,
    World,
    change_fee,
    move,
    reprice,
)
from tests.testpack.pack import DEPOSIT_ACCOUNT, LOADED_PACK
from tests.testpack.values import (
    ACTIVE,
    APPROVED,
    CLOSED,
    DENIED,
    FROZEN,
    INACTIVE,
    LOCKED,
    UNDER_REVIEW,
    LifecycleStatus,
    MonetaryAmount,
)

# A type with no status and no banking name, so an entity of it is always live
# and never the referent a deposit account's actions expect.
COUNTER = EntityType("COUNTER", relations={"amount": MonetaryAmount})
TWO_TYPES = replace(
    LOADED_PACK,
    entity_types={**LOADED_PACK.entity_types, COUNTER.name: COUNTER},
    action_types={
        **LOADED_PACK.action_types,
        "START_COUNTER": InitAction("START_COUNTER", referent_type="COUNTER"),
        "SET_COUNTER": MutateAction(
            "SET_COUNTER", referent_type="COUNTER", relation="amount"
        ),
    },
)


def _status(world: World, entity: NodeId) -> LifecycleStatus:
    entry = world.registry.entry(entity)
    assert entry is not None
    value = entry.values["hasStatus"].value
    assert isinstance(value, LifecycleStatus)
    return value


def _start_counter(world: World) -> NodeId:
    event, *_ = world.accept(
        InitCommand(
            session=1,
            initiator="CLIENT",
            action_type="START_COUNTER",
            source="customer",
            writes={"amount": MonetaryAmount(Decimal("1"))},
        )
    )
    assert isinstance(event, InitEvent)
    return event.new_id


# Closing is in the list because a terminal status is written by a MUTATE
# like any other, not by an event of its own.
@pytest.mark.parametrize(
    ("action_type", "status"),
    [("FREEZE_DEPOSIT_ACCOUNT", FROZEN), ("CLOSE_DEPOSIT_ACCOUNT", CLOSED)],
    ids=["freeze", "close"],
)
def test_a_status_move_is_a_mutate_writing_the_status_it_fixes(
    action_type: str, status: LifecycleStatus
) -> None:
    world = World()
    account = world.open()

    event, *_ = world.accept(move(account, 2, action_type))

    assert event == MutateEvent(
        session=2,
        initiator="BANK",
        action_type=action_type,
        referent=account,
        writes={"hasStatus": status},
    )


@pytest.mark.parametrize(
    ("moves", "expected"),
    [
        (["FREEZE_DEPOSIT_ACCOUNT", "UNFREEZE_DEPOSIT_ACCOUNT"], ACTIVE),
        (["CLOSE_DEPOSIT_ACCOUNT"], CLOSED),
        (["FREEZE_DEPOSIT_ACCOUNT", "CLOSE_DEPOSIT_ACCOUNT"], CLOSED),
    ],
    ids=["unfreeze from frozen", "close from active", "close from frozen"],
)
def test_a_move_from_one_of_its_source_statuses_is_accepted(
    moves: list[str], expected: LifecycleStatus
) -> None:
    world = World()
    account = world.open()

    for session, action_type in enumerate(moves, start=2):
        world.accept(move(account, session, action_type))

    assert _status(world, account) == expected


@pytest.mark.parametrize(
    ("earlier", "action_type"),
    [
        ("FREEZE_DEPOSIT_ACCOUNT", "FREEZE_DEPOSIT_ACCOUNT"),
        (None, "UNFREEZE_DEPOSIT_ACCOUNT"),
    ],
    ids=["freeze when frozen", "unfreeze when active"],
)
def test_a_move_from_outside_its_source_statuses_fails_the_gate(
    earlier: str | None, action_type: str
) -> None:
    world = World()
    account = world.open()
    if earlier is not None:
        world.accept(move(account, 2, earlier))

    outcome = world.decide(move(account, 3, action_type))

    assert outcome == Refusal(Reason.GATE_FAILED)


def test_a_closed_entity_stays_in_the_registry() -> None:
    world = World()
    account = world.open()

    world.accept(move(account, 2, "CLOSE_DEPOSIT_ACCOUNT"))

    assert account in world.registry.ids()


@pytest.mark.parametrize(
    ("command", "reason"),
    [
        (lambda account: reprice(account, 3, "3.90"), Reason.NOT_LIVE),
        (lambda account: change_fee(account, 3, "0"), Reason.NOT_LIVE),
        (
            lambda account: move(account, 3, "FREEZE_DEPOSIT_ACCOUNT"),
            Reason.GATE_FAILED,
        ),
        (
            lambda account: move(account, 3, "UNFREEZE_DEPOSIT_ACCOUNT"),
            Reason.GATE_FAILED,
        ),
        (
            lambda account: move(account, 3, "CLOSE_DEPOSIT_ACCOUNT"),
            Reason.GATE_FAILED,
        ),
    ],
    ids=["reprice", "change fee", "freeze", "unfreeze", "close again"],
)
def test_every_mutate_on_a_closed_entity_is_refused(
    command: Callable[[NodeId], MutateCommand], reason: Reason
) -> None:
    world = World()
    account = world.open()
    world.accept(move(account, 2, "CLOSE_DEPOSIT_ACCOUNT"))

    outcome = world.decide(command(account))

    assert outcome == Refusal(reason)


def test_a_gate_admitting_a_terminal_status_lets_a_closed_entity_act() -> None:
    waive_after_close = MutateAction(
        "WAIVE_FEE_AFTER_CLOSE",
        referent_type=DEPOSIT_ACCOUNT.name,
        relation="hasMonthlyFee",
        gate={"hasStatus": frozenset({CLOSED})},
    )
    pack = replace(
        LOADED_PACK,
        action_types={
            **LOADED_PACK.action_types,
            waive_after_close.name: waive_after_close,
        },
    )
    world = World(pack)
    account = world.open()

    def waive(session: int) -> MutateCommand:
        return replace(
            change_fee(account, session, "0"),
            action_type=waive_after_close.name,
        )

    refused_while_open = world.decide(waive(2))
    world.accept(move(account, 2, "CLOSE_DEPOSIT_ACCOUNT"))

    outcome = world.decide(waive(3))

    assert refused_while_open == Refusal(Reason.GATE_FAILED)
    assert not isinstance(outcome, Refusal)


def test_terminal_statuses_are_read_from_the_pack() -> None:
    frozen_is_terminal = replace(
        DEPOSIT_ACCOUNT, terminal=frozenset({FROZEN, CLOSED})
    )
    pack = replace(
        LOADED_PACK,
        entity_types={
            **LOADED_PACK.entity_types,
            DEPOSIT_ACCOUNT.name: frozen_is_terminal,
        },
    )

    def reprice_when_frozen(world: World) -> AcceptedCommand | Refusal:
        account = world.open()
        world.accept(move(account, 2, "FREEZE_DEPOSIT_ACCOUNT"))
        return world.decide(reprice(account, 3, "3.90"))

    usual_outcome = reprice_when_frozen(World())
    changed_outcome = reprice_when_frozen(World(pack))

    assert not isinstance(usual_outcome, Refusal)
    assert changed_outcome == Refusal(Reason.NOT_LIVE)


def test_a_command_whose_referent_does_not_exist_is_refused() -> None:
    world = World()
    world.open()

    outcome = world.decide(reprice(MISSING, 2, "3.90"))

    assert outcome == Refusal(Reason.REFERENT_MISSING)


def test_a_command_whose_referent_has_another_type_is_refused() -> None:
    world = World(TWO_TYPES)
    counter = _start_counter(world)

    outcome = world.decide(reprice(counter, 2, "3.90"))

    assert outcome == Refusal(Reason.REFERENT_WRONG_TYPE)


def test_an_entity_of_a_type_with_no_status_is_live() -> None:
    world = World(TWO_TYPES)
    counter = _start_counter(world)

    outcome = world.decide(
        MutateCommand(
            session=2,
            initiator="CLIENT",
            action_type="SET_COUNTER",
            source="customer",
            referent=counter,
            value=MonetaryAmount(Decimal("2")),
        )
    )

    assert not isinstance(outcome, Refusal)


def test_the_referent_clause_comes_before_the_write_clauses() -> None:
    world = World()
    account = world.open()
    world.accept(move(account, 2, "CLOSE_DEPOSIT_ACCOUNT"))

    # Also a second write of the pair in its session.
    outcome = world.decide(move(account, 2, "FREEZE_DEPOSIT_ACCOUNT"))

    assert outcome == Refusal(Reason.GATE_FAILED)


@pytest.mark.parametrize(
    "action_type", ["LOCK_CARD", "UNLOCK_CARD"], ids=["lock", "unlock"]
)
def test_an_inactive_card_cannot_be_locked_or_unlocked(
    action_type: str,
) -> None:
    world = World()
    card = world.issue_card(world.open())

    outcome = world.decide(move(card, 3, action_type))

    assert outcome == Refusal(Reason.GATE_FAILED)


def test_a_case_moves_through_review_appeal_and_closing() -> None:
    world = World()
    case = world.open_case()
    moves = (
        ("REVIEW_CASE", UNDER_REVIEW),
        ("DENY_CASE", DENIED),
        ("REVIEW_CASE", UNDER_REVIEW),
        ("APPROVE_CASE", APPROVED),
        ("CLOSE_CASE", CLOSED),
    )

    for session, (action, status) in enumerate(moves, start=REPORTED_IN + 1):
        world.accept(move(case, session, action))

        assert _status(world, case) == status


@pytest.mark.parametrize(
    "action", ["APPROVE_CASE", "DENY_CASE"], ids=["approve", "deny"]
)
def test_a_case_is_decided_only_under_review(action: str) -> None:
    world = World()
    case = world.open_case()

    outcome = world.decide(move(case, REPORTED_IN + 1, action))

    assert outcome == Refusal(Reason.GATE_FAILED)


def test_a_card_returning_to_active_has_a_status_node_per_write() -> None:
    world = World()
    card = world.issue_card(world.open())

    for session, action_type in enumerate(
        ["ACTIVATE_CARD", "LOCK_CARD", "UNLOCK_CARD"], start=3
    ):
        world.accept(move(card, session, action_type))

    chain = world.graph.update_chain((card, "hasStatus"))
    assert [node.value for node in chain] == [INACTIVE, ACTIVE, LOCKED, ACTIVE]
