from dataclasses import replace
from decimal import Decimal

import pytest

from mbench.core.folds.graph import EdgeKind, EntityNode, fold_trace
from mbench.core.folds.registry import Registry, Stamped, fold_world
from mbench.core.legality.predicate import Reason, Refusal, decide
from mbench.core.records.ids import IdAllocator
from mbench.core.records.log import Disclosure, InitEvent, Record
from mbench.core.values.protocol import ValueClass
from tests.core.world import (
    CARD_WRITES,
    ISSUED_IN,
    MISSING,
    OPENED_IN,
    REPORTED_IN,
    WRITES,
    World,
    issue,
    open_account,
    report_fraud,
)
from tests.testpack.pack import LOADED_PACK
from tests.testpack.values import (
    ACTIVE,
    CaseKind,
    LastFour,
    MonetaryAmount,
)


def _opening_records() -> tuple[Record, ...]:
    return World().accept(open_account(OPENED_IN))


def _split(
    records: tuple[Record, ...],
) -> tuple[list[InitEvent], list[Disclosure]]:
    events = [r for r in records if isinstance(r, InitEvent)]
    disclosures = [r for r in records if isinstance(r, Disclosure)]
    return events, disclosures


def test_accepting_an_init_gives_one_event_then_its_disclosures() -> None:
    first, *rest = _opening_records()

    assert isinstance(first, InitEvent)
    assert all(isinstance(record, Disclosure) for record in rest)


def test_the_init_event_carries_its_command_and_a_new_id() -> None:
    allocator = IdAllocator(seed=5)
    expected_id = IdAllocator(seed=5).allocate()

    outcome = decide(
        open_account(OPENED_IN), Registry(), LOADED_PACK, allocator
    )

    assert not isinstance(outcome, Refusal)
    (event,), _ = _split(outcome.records)
    assert event == InitEvent(
        session=OPENED_IN,
        initiator="CLIENT",
        action_type="OPEN_DEPOSIT_ACCOUNT",
        new_id=expected_id,
        writes=WRITES,
    )


def test_the_init_discloses_every_relation_it_writes_status_included() -> None:
    (event,), disclosures = _split(_opening_records())

    assert {(d.relation, d.value) for d in disclosures} == set(WRITES.items())
    assert len(disclosures) == len(WRITES)
    assert all(d.entity == event.new_id for d in disclosures)


def test_each_disclosure_has_its_own_node_id() -> None:
    (event,), disclosures = _split(_opening_records())
    ids = [event.new_id, *(d.node_id for d in disclosures)]

    assert len(set(ids)) == len(ids)


def test_each_disclosure_is_framed_by_its_event_and_names_the_source() -> None:
    (event,), disclosures = _split(_opening_records())

    assert all(d.session == event.session for d in disclosures)
    assert all(d.action_type == event.action_type for d in disclosures)
    assert all(d.initiator == event.initiator for d in disclosures)
    assert all(d.source == "customer" for d in disclosures)


def test_the_registry_holds_one_entry_with_every_value_stamped() -> None:
    records = _opening_records()
    (event,), _ = _split(records)

    registry = fold_world(records, LOADED_PACK)

    assert registry.ids() == {event.new_id}
    entry = registry.entry(event.new_id)
    assert entry is not None
    assert entry.type == "DEPOSIT_ACCOUNT"
    assert entry.id == event.new_id
    assert entry.values == {
        relation: Stamped(value, OPENED_IN)
        for relation, value in WRITES.items()
    }


def test_the_graph_holds_the_entity_and_one_value_node_per_relation() -> None:
    records = _opening_records()
    (event,), disclosures = _split(records)

    graph = fold_trace(records, LOADED_PACK)

    assert graph.entity_nodes() == {EntityNode(event.new_id, "DEPOSIT_ACCOUNT")}
    assert {node.id for node in graph.value_nodes()} == {
        d.node_id for d in disclosures
    }
    value_edges = {
        (edge.source, edge.relation, edge.target)
        for edge in graph.edges()
        if edge.kind is EdgeKind.VALUE
    }
    assert value_edges == {
        (event.new_id, d.relation, d.node_id) for d in disclosures
    }


def test_every_node_has_exactly_one_occurred_in_edge_to_the_session() -> None:
    graph = fold_trace(_opening_records(), LOADED_PACK)
    nodes = {node.id for node in graph.entity_nodes() | graph.value_nodes()}

    occurred = [
        edge for edge in graph.edges() if edge.kind is EdgeKind.OCCURRED_IN
    ]

    assert sorted(edge.source for edge in occurred) == sorted(nodes)
    assert {edge.target for edge in occurred} == {OPENED_IN}
    assert graph.session_nodes() == {OPENED_IN}


@pytest.mark.parametrize(
    "changes",
    [
        {"lastFour": LastFour("44a1")},
        {"hasInterestRate": MonetaryAmount(Decimal("4.25"))},
        {"noSuchRelation": LastFour("1234")},
    ],
    ids=["invalid value", "value of another class", "relation the type lacks"],
)
def test_a_value_the_relation_does_not_hold_is_refused_not_raised(
    changes: dict[str, ValueClass],
) -> None:
    outcome = World().decide(open_account(OPENED_IN, **changes))

    assert outcome == Refusal(clause=3, reason=Reason.INVALID_VALUE)


def test_a_refused_command_allocates_no_id() -> None:
    allocator = IdAllocator(seed=9)
    command = open_account(OPENED_IN, lastFour=LastFour("44a1"))

    decide(command, Registry(), LOADED_PACK, allocator)

    assert allocator.allocate() == IdAllocator(seed=9).allocate()


@pytest.mark.parametrize(
    "writes",
    [
        {r: v for r, v in CARD_WRITES.items() if r != "hasStatus"},
        {**CARD_WRITES, "hasStatus": ACTIVE},
    ],
    ids=["omitted", "another status"],
)
def test_a_wrong_entry_status_raises_before_any_clause_refuses(
    writes: dict[str, ValueClass],
) -> None:
    # The missing endpoint would be refused by the first clause an INIT meets.
    command = replace(issue(MISSING, ISSUED_IN), writes=writes)

    with pytest.raises(ValueError, match="hasStatus"):
        World().decide(command)


def test_a_fixed_value_other_than_the_status_is_held_too() -> None:
    world = World()
    card = world.issue_card(world.open())
    command = report_fraud(card, REPORTED_IN, kind=CaseKind("card_request"))

    with pytest.raises(ValueError, match="kind"):
        world.decide(command)
