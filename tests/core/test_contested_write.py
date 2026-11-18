from collections.abc import Callable
from dataclasses import replace
from decimal import Decimal

import pytest

from mbench.core.folds.graph import Edge, EdgeKind, fold_trace
from mbench.core.folds.registry import Stamped
from mbench.core.legality.predicate import (
    Reason,
    Refusal,
    refuse_untrue_disclosure,
)
from mbench.core.records.commands import ConflictingDoubleDisclosureCommand
from mbench.core.records.ids import NodeId
from mbench.core.records.log import CONTEST, Disclosure, MutateEvent
from mbench.core.values.contested import Contested, WorldValue
from mbench.core.values.protocol import ValueClass
from tests.core.world import (
    BANK_MAY_CLOSE,
    MISSING,
    OPENED_IN,
    OPENING_RATE,
    WRITES,
    World,
    contest,
    disclosures_in,
    move,
    reprice,
    status_contest,
)
from tests.testpack.pack import LOADED_PACK
from tests.testpack.values import (
    CLOSED,
    FROZEN,
    InterestRate,
    MonetaryAmount,
)

RATE = "hasInterestRate"
REPRICED_IN = 5
CONTESTED_IN = 7
A = "3.75"
B = "3.60"
REPRICED = "3.90"
A_VALUE = InterestRate(Decimal(A))
B_VALUE = InterestRate(Decimal(B))
OPENING_VALUE = InterestRate(Decimal(OPENING_RATE))
REPRICED_VALUE = InterestRate(Decimal(REPRICED))


def test_accepting_gives_one_contest_mutate_and_a_disclosure_per_value() -> (
    None
):
    world = World()
    account = world.open()

    records = world.accept(contest(account, CONTESTED_IN, A, B))

    assert [type(r) for r in records] == [
        MutateEvent,
        Disclosure,
        Disclosure,
    ]
    assert records[0] == MutateEvent(
        session=CONTESTED_IN,
        initiator="BANK",
        action_type=CONTEST,
        referent=account,
        writes={RATE: Contested(A_VALUE, B_VALUE)},
    )
    assert [
        (d.source, d.session, d.entity, d.relation, d.value)
        for d in disclosures_in(records)
    ] == [
        ("letter", CONTESTED_IN, account, RATE, A_VALUE),
        ("email", CONTESTED_IN, account, RATE, B_VALUE),
    ]


def test_each_disclosure_is_framed_by_the_action_writing_its_own_value() -> (
    None
):
    world = World(BANK_MAY_CLOSE)
    account = world.open()
    command = status_contest(account, CONTESTED_IN, FROZEN, CLOSED)

    disclosures = disclosures_in(world.accept(command))

    assert [(d.value, d.action_type, d.initiator) for d in disclosures] == [
        (FROZEN, "FREEZE_DEPOSIT_ACCOUNT", "BANK"),
        (CLOSED, "CLOSE_DEPOSIT_ACCOUNT", "BANK"),
    ]


def test_one_document_may_state_both_values() -> None:
    world = World()
    account = world.open()
    command = contest(account, CONTESTED_IN, A, B, sources=("letter", "letter"))

    disclosures = disclosures_in(world.accept(command))

    assert [d.source for d in disclosures] == ["letter", "letter"]


def test_a_source_the_pack_does_not_declare_raises() -> None:
    world = World()
    account = world.open()
    command = contest(account, CONTESTED_IN, A, B, sources=("letter", "pigeon"))

    with pytest.raises(ValueError, match="pigeon"):
        world.decide(command)


def test_the_registry_holds_the_conflict_and_no_true_value() -> None:
    world = World()
    account = world.open()
    world.accept(contest(account, CONTESTED_IN, A, B))

    entry = world.registry.entry(account)

    assert entry is not None
    assert entry.values[RATE] == Stamped(
        Contested(A_VALUE, B_VALUE), CONTESTED_IN
    )


def test_the_latest_value_is_both_nodes_created_in_one_session() -> None:
    world = World()
    account = world.open()
    first, second = disclosures_in(
        world.accept(contest(account, CONTESTED_IN, A, B))
    )

    graph = world.graph
    latest = graph.latest((account, RATE))

    assert {(node.id, node.value) for node in latest} == {
        (first.node_id, A_VALUE),
        (second.node_id, B_VALUE),
    }
    assert {
        Edge(EdgeKind.OCCURRED_IN, first.node_id, CONTESTED_IN),
        Edge(EdgeKind.OCCURRED_IN, second.node_id, CONTESTED_IN),
    } <= graph.edges()


def test_a_conflicts_two_nodes_chain_by_id_in_either_fold_order() -> None:
    world = World()
    account = world.open()
    world.accept(reprice(account, REPRICED_IN, REPRICED))
    earlier = world.records
    event, first, second = world.accept(contest(account, CONTESTED_IN, A, B))
    assert isinstance(first, Disclosure)
    assert isinstance(second, Disclosure)

    # A set of two ids iterates in an order set by the run's string hashes, so
    # one pair could come out sorted by luck, but twenty will not.
    for n in range(20):
        low, high = NodeId(f"a{n:04d}"), NodeId(f"b{n:04d}")
        stating_a = replace(first, node_id=high)
        stating_b = replace(second, node_id=low)

        for halves in ((stating_a, stating_b), (stating_b, stating_a)):
            graph = fold_trace((*earlier, event, *halves), LOADED_PACK)

            chain = graph.update_chain((account, RATE))

            assert [node.value for node in chain] == [
                OPENING_VALUE,
                REPRICED_VALUE,
                B_VALUE,
                A_VALUE,
            ]
            assert [node.id for node in chain[2:]] == [low, high]


def _held(value: WorldValue) -> frozenset[ValueClass]:
    """The values a registry value stands for in the graph's latest."""

    return value.members if isinstance(value, Contested) else frozenset({value})


def test_the_registry_and_the_graph_agree_on_every_pair() -> None:
    world = World()
    account = world.open()
    world.accept(contest(account, CONTESTED_IN, A, B))

    entry = world.registry.entry(account)
    graph = world.graph

    assert entry is not None
    assert entry.values.keys() == WRITES.keys()
    for relation, current in entry.values.items():
        latest = graph.latest((account, relation))
        assert {node.value for node in latest} == _held(current.value)


def test_a_conflict_is_the_same_whichever_value_is_named_first() -> None:
    assert Contested(A_VALUE, B_VALUE) == Contested(B_VALUE, A_VALUE)
    assert hash(Contested(A_VALUE, B_VALUE)) == hash(
        Contested(B_VALUE, A_VALUE)
    )


def test_a_conflict_differs_from_another_pair_and_from_a_plain_value() -> None:
    conflict = Contested(A_VALUE, B_VALUE)

    assert conflict != Contested(A_VALUE, REPRICED_VALUE)
    assert conflict != A_VALUE


def test_a_stored_disclosure_of_either_value_is_true_and_of_another_not() -> (
    None
):
    world = World()
    account = world.open()
    first, second = disclosures_in(
        world.accept(contest(account, CONTESTED_IN, A, B))
    )
    registry = world.registry
    stale = replace(first, value=OPENING_VALUE)

    assert refuse_untrue_disclosure(first, registry) is None
    assert refuse_untrue_disclosure(second, registry) is None
    assert refuse_untrue_disclosure(stale, registry) == Refusal(
        4, Reason.UNTRUE_DISCLOSURE
    )


@pytest.mark.parametrize(
    ("command", "refusal"),
    [
        (
            lambda _: contest(MISSING, CONTESTED_IN, A, B),
            Refusal(1, Reason.REFERENT_MISSING),
        ),
        (
            lambda account: contest(account, OPENED_IN, A, B),
            Refusal(2, Reason.PAIR_ALREADY_WRITTEN),
        ),
        (
            lambda account: replace(
                contest(account, CONTESTED_IN, A, B),
                a=MonetaryAmount(Decimal("1")),
            ),
            Refusal(3, Reason.INVALID_VALUE),
        ),
        (
            lambda account: replace(
                contest(account, CONTESTED_IN, A, B),
                b=InterestRate(Decimal("100")),
            ),
            Refusal(3, Reason.INVALID_VALUE),
        ),
        (
            lambda account: replace(
                contest(account, CONTESTED_IN, A, B), relation="hasNoSuchThing"
            ),
            Refusal(3, Reason.INVALID_VALUE),
        ),
    ],
    ids=[
        "missing referent",
        "pair written this session",
        "a of another class",
        "b invalid",
        "relation no type has",
    ],
)
def test_a_contested_write_is_refused_like_any_other_write(
    command: Callable[[NodeId], ConflictingDoubleDisclosureCommand],
    refusal: Refusal,
) -> None:
    world = World()
    account = world.open()

    assert world.decide(command(account)) == refusal


def test_a_contested_write_on_a_closed_referent_is_refused() -> None:
    world = World()
    account = world.open()
    world.accept(move(account, CONTESTED_IN - 1, "CLOSE_DEPOSIT_ACCOUNT"))

    outcome = world.decide(contest(account, CONTESTED_IN, A, B))

    assert outcome == Refusal(1, Reason.NOT_LIVE)


def test_contesting_a_relation_the_referent_type_lacks_is_refused() -> None:
    world = World()
    card = world.issue_card(world.open())

    outcome = world.decide(contest(card, CONTESTED_IN, A, B))

    assert outcome == Refusal(3, Reason.INVALID_VALUE)
