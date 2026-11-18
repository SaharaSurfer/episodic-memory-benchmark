from collections.abc import Mapping
from dataclasses import replace

import pytest

from mbench.core.folds.graph import Edge, EdgeKind, fold_trace
from mbench.core.folds.registry import fold_world
from mbench.core.legality.predicate import (
    Reason,
    Refusal,
    refuse_untrue_disclosure,
)
from mbench.core.records.ids import NodeId
from mbench.core.records.log import (
    AcceptedCommand,
    Disclosure,
    InitEvent,
    Link,
)
from mbench.packs.spec import Gate, InitAction
from tests.core.world import (
    CARD_LINK,
    CARD_WRITES,
    ISSUED_IN,
    World,
    issue,
    move,
)
from tests.testpack.pack import LOADED_PACK, PAYMENT_CARD
from tests.testpack.values import DepositKind, LastFour, LifecycleStatus

MISSING = NodeId("zzzzz")


def _with_endpoint_gate(gate: Gate) -> World:
    action = InitAction(
        "ISSUE_CARD", referent_type=PAYMENT_CARD.name, links={CARD_LINK: gate}
    )
    pack = replace(
        LOADED_PACK,
        action_types={**LOADED_PACK.action_types, action.name: action},
    )
    return World(pack)


def test_the_init_event_carries_its_links_beside_its_values() -> None:
    world = World()
    account = world.open()

    event, *_ = world.accept(issue(account, ISSUED_IN))

    assert isinstance(event, InitEvent)
    assert event.links == {CARD_LINK: account}
    assert event.writes == CARD_WRITES


def test_an_init_discloses_its_link_by_default() -> None:
    world = World()
    account = world.open()

    event, *rest = world.accept(issue(account, ISSUED_IN))

    assert isinstance(event, InitEvent)
    (disclosure,) = [
        d for d in rest if isinstance(d, Disclosure) and d.relation == CARD_LINK
    ]
    assert disclosure == Disclosure(
        session=ISSUED_IN,
        source="operator",
        action_type="ISSUE_CARD",
        initiator="BANK",
        entity=event.new_id,
        relation=CARD_LINK,
        value=Link(account),
        node_id=disclosure.node_id,
    )


def test_a_link_is_a_structural_edge_and_not_a_value_node() -> None:
    world = World()
    account = world.open()

    card = world.issue_card(account)

    graph = fold_trace(world.records, world.pack)
    structural = {e for e in graph.edges() if e.kind is EdgeKind.STRUCTURAL}
    assert structural == {Edge(EdgeKind.STRUCTURAL, card, account, CARD_LINK)}
    assert graph.versions((card, CARD_LINK)) == 0
    assert graph.versions((card, "lastFour")) == 1


def test_the_registry_entry_holds_the_link() -> None:
    world = World()
    account = world.open()

    card = world.issue_card(account)

    registry = fold_world(world.records, world.pack)
    card_entry, account_entry = registry.entry(card), registry.entry(account)
    assert card_entry is not None
    assert account_entry is not None
    assert card_entry.links == {CARD_LINK: account}
    assert CARD_LINK not in card_entry.values
    assert account_entry.links == {}


def test_later_writes_to_the_card_keep_its_link() -> None:
    world = World()
    account = world.open()
    card = world.issue_card(account)

    world.accept(move(card, 3, "ACTIVATE_CARD"))
    world.accept(move(card, 4, "LOCK_CARD"))

    entry = fold_world(world.records, world.pack).entry(card)
    assert entry is not None
    assert entry.links == {CARD_LINK: account}


def test_an_endpoint_that_does_not_exist_is_refused() -> None:
    world = World()

    outcome = world.decide(issue(MISSING, ISSUED_IN))

    assert outcome == Refusal(clause=1, reason=Reason.ENDPOINT_MISSING)


def test_an_endpoint_of_a_type_the_link_does_not_point_at_is_refused() -> None:
    world = World()
    card = world.issue_card(world.open())

    outcome = world.decide(issue(card, 3))

    assert outcome == Refusal(clause=1, reason=Reason.ENDPOINT_WRONG_TYPE)


def test_an_endpoint_failing_its_gate_is_refused() -> None:
    world = _with_endpoint_gate(
        {"hasStatus": frozenset({LifecycleStatus("active")})}
    )
    account = world.open()
    passing = world.decide(issue(account, 2))
    world.accept(move(account, 2, "FREEZE_DEPOSIT_ACCOUNT"))

    outcome = world.decide(issue(account, 3))

    assert not isinstance(passing, Refusal)
    assert outcome == Refusal(clause=1, reason=Reason.ENDPOINT_GATE_FAILED)


def test_an_endpoint_failing_its_filter_is_refused() -> None:
    world = World()
    account = world.open()  # a savings account

    def wanting(kind: str) -> AcceptedCommand | Refusal:
        command = replace(
            issue(account, ISSUED_IN),
            filters={CARD_LINK: {"kind": frozenset({DepositKind(kind)})}},
        )
        return world.decide(command)

    assert not isinstance(wanting("savings"), Refusal)
    assert wanting("checking") == Refusal(
        clause=1, reason=Reason.ENDPOINT_FILTER_FAILED
    )


def test_an_endpoint_need_not_be_live() -> None:
    world = World()
    account = world.open()
    world.accept(move(account, 2, "CLOSE_DEPOSIT_ACCOUNT"))

    outcome = world.decide(issue(account, 3))

    assert not isinstance(outcome, Refusal)


def test_the_endpoint_clause_comes_before_the_value_clause() -> None:
    world = World()
    invalid = {**CARD_WRITES, "lastFour": LastFour("12")}

    outcome = world.decide(replace(issue(MISSING, ISSUED_IN), writes=invalid))

    assert outcome == Refusal(clause=1, reason=Reason.ENDPOINT_MISSING)


@pytest.mark.parametrize(
    "links",
    [{}, {CARD_LINK: MISSING, "replaces": MISSING}],
    ids=["missing", "undeclared"],
)
def test_an_init_must_name_exactly_the_links_it_writes(
    links: Mapping[str, NodeId],
) -> None:
    world = World()

    with pytest.raises(ValueError, match="links"):
        world.decide(replace(issue(MISSING, ISSUED_IN), links=links))


def test_a_filter_on_a_link_the_init_does_not_write_is_a_caller_bug() -> None:
    world = World()

    with pytest.raises(ValueError, match="filter"):
        world.decide(
            replace(issue(MISSING, ISSUED_IN), filters={"replaces": {}})
        )


def test_a_link_disclosure_is_true_only_of_the_linked_target() -> None:
    world = World()
    account = world.open()
    other = world.open()
    card = world.issue_card(account)
    registry = fold_world(world.records, world.pack)

    def stating(entity: NodeId, target: NodeId) -> Refusal | None:
        disclosure = Disclosure(
            session=3,
            source="operator",
            action_type="ISSUE_CARD",
            initiator="BANK",
            entity=entity,
            relation=CARD_LINK,
            value=Link(target),
            node_id=NodeId("aaaaa"),
        )
        return refuse_untrue_disclosure(disclosure, registry)

    untrue = Refusal(clause=4, reason=Reason.UNTRUE_DISCLOSURE)
    assert stating(card, account) is None
    assert stating(card, other) == untrue
    assert stating(account, other) == untrue
