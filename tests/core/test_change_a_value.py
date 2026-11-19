from collections.abc import Callable
from dataclasses import replace
from decimal import Decimal

import pytest

from mbench.core.folds.graph import (
    EdgeKind,
    Graph,
    fold_trace,
)
from mbench.core.folds.registry import Stamped
from mbench.core.records.commands import Command, InitCommand, MutateCommand
from mbench.core.records.ids import NodeId
from mbench.core.records.log import Disclosure, MutateEvent
from tests.core.records.handmade import disclosure_of
from tests.core.world import (
    OPENED_IN,
    WRITES,
    World,
    change_fee,
    move,
    reprice,
)
from tests.testpack.pack import LOADED_PACK
from tests.testpack.values import (
    CLOSED,
    InterestRate,
    LastFour,
    MonetaryAmount,
)


def _session_of(graph: Graph, node: NodeId) -> int | str:
    (session,) = {
        edge.target
        for edge in graph.edges()
        if edge.kind is EdgeKind.OCCURRED_IN and edge.source == node
    }
    return session


def test_a_mutate_gives_one_event_with_its_referent_and_one_value() -> None:
    world = World()
    account = world.open()

    event, *_ = world.accept(reprice(account, 2, "3.90"))

    assert event == MutateEvent(
        session=2,
        initiator="BANK",
        action_type="REPRICE_DEPOSIT_ACCOUNT",
        referent=account,
        writes={"hasInterestRate": InterestRate(Decimal("3.90"))},
    )


def test_a_mutate_discloses_its_one_value_framed_by_its_event() -> None:
    world = World()
    account = world.open()
    used = {r.node_id for r in world.records if isinstance(r, Disclosure)}

    _, *disclosures = world.accept(change_fee(account, 2, "0"))

    (disclosure,) = disclosures
    assert isinstance(disclosure, Disclosure)
    assert disclosure.node_id not in used | {account}
    assert disclosure == Disclosure(
        session=2,
        source="letter",
        action_type="CHANGE_ACCOUNT_FEE",
        initiator="BANK",
        entity=account,
        relation="hasMonthlyFee",
        value=MonetaryAmount(Decimal("0")),
        node_id=disclosure.node_id,
    )


def test_after_a_mutate_the_registry_holds_the_new_value_and_stamp() -> None:
    world = World()
    account = world.open()
    world.accept(change_fee(account, 2, "0"))

    entry = world.registry.entry(account)

    assert entry is not None
    assert entry.type == "DEPOSIT_ACCOUNT"
    assert entry.values == {
        **{
            relation: Stamped(value, OPENED_IN)
            for relation, value in WRITES.items()
        },
        "hasMonthlyFee": Stamped(MonetaryAmount(Decimal("0")), 2),
    }


def test_a_mutate_leaves_other_entities_unchanged() -> None:
    world = World()
    account = world.open()
    other = world.open()
    before = world.registry.entry(other)

    world.accept(change_fee(account, 2, "0"))

    assert world.registry.entry(other) == before


def test_the_entity_keeps_the_session_of_its_init() -> None:
    world = World()
    account = world.open()
    world.accept(change_fee(account, 2, "0"))

    graph = world.graph

    assert _session_of(graph, account) == OPENED_IN


def test_the_graph_answers_a_pairs_chain_versions_and_latest_node() -> None:
    world = World()
    account = world.open()
    world.accept(reprice(account, 2, "3.90"))
    _, disclosure = world.accept(reprice(account, 4, "3.50"))
    assert isinstance(disclosure, Disclosure)

    graph = world.graph
    pair = (account, "hasInterestRate")

    chain = graph.update_chain(pair)
    assert chain[-1].id == disclosure.node_id
    assert [node.value for node in chain] == [
        InterestRate(Decimal("4.25")),
        InterestRate(Decimal("3.90")),
        InterestRate(Decimal("3.50")),
    ]
    assert [_session_of(graph, node.id) for node in chain] == [1, 2, 4]
    assert graph.versions(pair) == 3
    assert graph.latest(pair) == {chain[-1]}


def test_a_mutate_leaves_another_relations_chain_at_one() -> None:
    world = World()
    account = world.open()
    world.accept(reprice(account, 2, "3.90"))

    graph = world.graph
    pair = (account, "lastFour")

    assert graph.versions(pair) == 1
    assert graph.latest(pair) == set(graph.update_chain(pair))


def test_a_pair_never_disclosed_has_an_empty_chain() -> None:
    graph = Graph()
    pair = (NodeId("aaaaa"), "hasMonthlyFee")

    assert graph.update_chain(pair) == ()
    assert graph.versions(pair) == 0
    assert graph.latest(pair) == frozenset()


def test_version_order_comes_from_sessions_not_from_record_order() -> None:
    world = World()
    account = world.open()
    opening = world.records
    second = world.accept(reprice(account, 2, "3.90"))
    third = world.accept(reprice(account, 3, "3.50"))

    in_order = fold_trace(opening + second + third, LOADED_PACK)
    swapped = fold_trace(opening + third + second, LOADED_PACK)

    assert swapped == in_order
    assert [
        node.value
        for node in swapped.update_chain((account, "hasInterestRate"))
    ] == [
        InterestRate(Decimal("4.25")),
        InterestRate(Decimal("3.90")),
        InterestRate(Decimal("3.50")),
    ]


def test_a_chain_returning_to_an_earlier_value_counts_every_write() -> None:
    world = World()
    account = world.open()
    world.accept(change_fee(account, 2, "0"))
    world.accept(change_fee(account, 3, "5"))

    graph = world.graph
    pair = (account, "hasMonthlyFee")

    chain = graph.update_chain(pair)
    assert graph.versions(pair) == 3
    assert [node.value for node in chain] == [
        MonetaryAmount(Decimal("5")),
        MonetaryAmount(Decimal("0")),
        MonetaryAmount(Decimal("5")),
    ]
    assert graph.latest(pair) == {chain[-1]}


@pytest.mark.parametrize(
    ("command", "message"),
    [
        (
            lambda account: MutateCommand(
                session=2,
                initiator="BANK",
                action_type="OPEN_DEPOSIT_ACCOUNT",
                source="letter",
                referent=account,
                value=MonetaryAmount(Decimal("0")),
            ),
            "MutateCommand cannot take OPEN_DEPOSIT_ACCOUNT",
        ),
        (
            lambda _: InitCommand(
                session=2,
                initiator="CLIENT",
                action_type="CHANGE_ACCOUNT_FEE",
                source="customer",
                writes=WRITES,
            ),
            "InitCommand cannot take CHANGE_ACCOUNT_FEE",
        ),
    ],
    ids=["mutate naming an init", "init naming a mutate"],
)
def test_a_command_naming_an_action_of_the_other_shape_raises(
    command: Callable[[NodeId], Command], message: str
) -> None:
    world = World()
    account = world.open()

    with pytest.raises(TypeError, match=message):
        world.decide(command(account))


@pytest.mark.parametrize(
    "command",
    [
        lambda account: replace(
            move(account, 2, "FREEZE_DEPOSIT_ACCOUNT"),
            value=CLOSED,
        ),
        lambda account: replace(reprice(account, 2, "3.90"), value=None),
    ],
    ids=["status move naming a value", "value mutate naming none"],
)
def test_a_mutate_naming_a_value_its_action_fixes_or_needs_raises(
    command: Callable[[NodeId], MutateCommand],
) -> None:
    world = World()
    account = world.open()

    with pytest.raises(TypeError, match="needs a value"):
        world.decide(command(account))


def test_a_later_disclosure_may_name_an_action_the_pack_lacks() -> None:
    world = World()
    account = world.open()
    # A value other than the current one, so it is a new node, not a mention.
    later = disclosure_of(
        account,
        "lastFour",
        LastFour("9012"),
        session=2,
        action_type="NOT_A_PACK_ACTION",
    )

    graph = fold_trace((*world.records, later), LOADED_PACK)

    assert graph.versions((account, "lastFour")) == 2
    assert {node.type for node in graph.entity_nodes()} == {"DEPOSIT_ACCOUNT"}
