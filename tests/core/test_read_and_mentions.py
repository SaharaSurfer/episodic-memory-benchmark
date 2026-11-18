from collections.abc import Callable
from dataclasses import replace
from decimal import Decimal

import pytest

from mbench.core.folds.graph import Edge, EdgeKind, Graph, fold_trace
from mbench.core.folds.registry import fold_world
from mbench.core.legality.predicate import (
    Reason,
    Refusal,
    refuse_untrue_disclosure,
)
from mbench.core.records.ids import NodeId
from mbench.core.records.log import READ, Disclosure
from tests.core.world import (
    OPENED_IN,
    OPENING_RATE,
    WRITES,
    World,
    change_fee,
    disclosures_in,
    read,
    reprice,
)
from tests.testpack.pack import LOADED_PACK
from tests.testpack.values import InterestRate

RATE = "hasInterestRate"


def _said_in(graph: Graph) -> set[Edge]:
    return {edge for edge in graph.edges() if edge.kind is EdgeKind.SAID_IN}


def test_a_read_gives_one_disclosure_per_current_value_and_no_event() -> None:
    world = World()
    account = world.open()

    records = world.accept(read(account, 3))

    disclosures = disclosures_in(records)
    assert len(disclosures) == len(records)
    assert {(d.relation, d.value) for d in disclosures} == set(WRITES.items())
    assert len(disclosures) == len(WRITES)


def test_a_read_is_framed_read_with_the_initiator_and_source_it_names() -> None:
    world = World()
    account = world.open()
    command = replace(read(account, 3), initiator="BANK", source="letter")

    disclosures = disclosures_in(world.accept(command))

    assert {
        (d.session, d.source, d.action_type, d.initiator, d.entity)
        for d in disclosures
    } == {(3, "letter", READ, "BANK", account)}


def test_every_read_disclosure_carries_a_fresh_node_id() -> None:
    world = World()
    account = world.open()
    used = {account} | {d.node_id for d in disclosures_in(world.records)}

    disclosures = disclosures_in(world.accept(read(account, 3)))

    ids = {d.node_id for d in disclosures}
    assert len(ids) == len(disclosures)
    assert not ids & used


def test_a_mention_is_one_said_in_edge_from_each_value_node() -> None:
    world = World()
    account = world.open()
    opening = world.records
    before = fold_trace(opening, LOADED_PACK)

    world.accept(read(account, 3))

    graph = fold_trace(world.records, LOADED_PACK)
    opened = {d.node_id for d in disclosures_in(opening)}
    assert _said_in(graph) == {
        Edge(EdgeKind.SAID_IN, node, 3) for node in opened
    }
    assert graph.value_nodes() == before.value_nodes()
    assert graph.entity_nodes() == before.entity_nodes()
    assert graph.session_nodes() == {OPENED_IN, 3}


def test_a_second_read_in_the_same_session_adds_nothing() -> None:
    world = World()
    account = world.open()
    world.accept(read(account, 3))
    once = fold_trace(world.records, LOADED_PACK)

    world.accept(read(account, 3))

    assert fold_trace(world.records, LOADED_PACK) == once


def test_a_read_in_the_session_of_the_write_adds_nothing() -> None:
    world = World()
    account = world.open()
    written = fold_trace(world.records, LOADED_PACK)

    world.accept(read(account, OPENED_IN))

    assert fold_trace(world.records, LOADED_PACK) == written


def test_a_read_in_a_session_before_the_write_is_no_mention() -> None:
    world = World()
    account = world.open()
    world.accept(reprice(account, 3, "3.90"))

    world.accept(read(account, 2))

    graph = fold_trace(world.records, LOADED_PACK)
    (latest,) = graph.latest((account, RATE))
    assert graph.mentions(latest.id) == frozenset()


def test_reads_in_two_later_sessions_give_two_mentions() -> None:
    world = World()
    account = world.open()
    world.accept(read(account, 3))
    world.accept(read(account, 5))

    graph = fold_trace(world.records, LOADED_PACK)

    (node,) = graph.latest((account, RATE))
    assert graph.mentions(node.id) == {3, 5}


def test_mentions_carry_over_a_fold_started_from_a_graph() -> None:
    world = World()
    account = world.open()
    world.accept(read(account, 3))
    first = world.records
    world.accept(read(account, 5))
    second = world.records[len(first) :]

    resumed = fold_trace(second, LOADED_PACK, fold_trace(first, LOADED_PACK))

    assert resumed == fold_trace(first + second, LOADED_PACK)
    (node,) = resumed.latest((account, RATE))
    assert resumed.mentions(node.id) == {3, 5}


def test_after_a_mutate_a_read_mentions_the_newest_node_only() -> None:
    world = World()
    account = world.open()
    world.accept(reprice(account, 2, "3.90"))

    disclosures = disclosures_in(world.accept(read(account, 3)))

    (rate,) = [d for d in disclosures if d.relation == RATE]
    assert rate.value == InterestRate(Decimal("3.90"))
    graph = fold_trace(world.records, LOADED_PACK)
    old, new = graph.update_chain((account, RATE))
    assert graph.mentions(new.id) == {3}
    assert graph.mentions(old.id) == frozenset()


def test_a_read_after_a_return_to_a_value_mentions_the_return() -> None:
    world = World()
    account = world.open()
    world.accept(change_fee(account, 2, "0"))
    world.accept(change_fee(account, 3, "5"))
    world.accept(read(account, 4))

    graph = fold_trace(world.records, LOADED_PACK)

    first, _, back = graph.update_chain((account, "hasMonthlyFee"))
    assert first.value == back.value
    assert graph.mentions(back.id) == {4}
    assert graph.mentions(first.id) == frozenset()


def test_a_read_of_an_entity_that_does_not_exist_is_refused() -> None:
    world = World()
    world.open()

    outcome = world.decide(read(NodeId("zzzzz"), 3))

    assert outcome == Refusal(1, Reason.REFERENT_MISSING)


def _stating(entity: NodeId, rate: str) -> Disclosure:
    return Disclosure(
        session=3,
        source="operator",
        action_type=READ,
        initiator="CLIENT",
        entity=entity,
        relation=RATE,
        value=InterestRate(Decimal(rate)),
        node_id=NodeId("zzzzz"),
    )


def test_a_disclosure_of_the_current_value_is_admitted() -> None:
    world = World()
    account = world.open()
    world.accept(reprice(account, 2, "3.90"))
    registry = fold_world(world.records, LOADED_PACK)

    disclosure = _stating(account, "3.90")

    assert refuse_untrue_disclosure(disclosure, registry) is None


@pytest.mark.parametrize(
    "rate", [OPENING_RATE, "9.99"], ids=["stale", "invented"]
)
def test_a_disclosure_of_a_value_not_current_is_refused(rate: str) -> None:
    world = World()
    account = world.open()
    world.accept(reprice(account, 2, "3.90"))
    registry = fold_world(world.records, LOADED_PACK)

    disclosure = _stating(account, rate)

    assert refuse_untrue_disclosure(disclosure, registry) == Refusal(
        4, Reason.UNTRUE_DISCLOSURE
    )


@pytest.mark.parametrize(
    "missing",
    [
        lambda account: _stating(NodeId("zzzzz"), OPENING_RATE),
        lambda account: replace(
            _stating(account, OPENING_RATE), relation="notARelation"
        ),
    ],
    ids=["unknown_entity", "unknown_relation"],
)
def test_a_disclosure_about_a_pair_the_world_lacks_is_refused(
    missing: Callable[[NodeId], Disclosure],
) -> None:
    world = World()
    account = world.open()
    registry = fold_world(world.records, LOADED_PACK)

    disclosure = missing(account)

    assert refuse_untrue_disclosure(disclosure, registry) == Refusal(
        4, Reason.UNTRUE_DISCLOSURE
    )
